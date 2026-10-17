using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace InvestorIntelligence
{
    internal interface INativeCredentialApi
    {
        bool CredWrite(ref NativeCredential credential, uint flags);
        bool CredRead(string targetName, uint type, uint reservedFlag, out IntPtr credentialPtr);
        bool CredDelete(string targetName, uint type, uint flags);
        void CredFree(IntPtr buffer);
        int GetLastWin32Error();
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    internal struct NativeCredential
    {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public IntPtr Comment;
        public uint LastWrittenLow;
        public uint LastWrittenHigh;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public IntPtr TargetAlias;
        public IntPtr UserName;
    }

    internal sealed class Advapi32NativeCredentialApi : INativeCredentialApi
    {
        [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool NativeCredWrite([In] ref NativeCredential userCredential, [In] uint flags);

        [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool NativeCredRead([In] string targetName, [In] uint type, [In] uint reservedFlag, out IntPtr credentialPtr);

        [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool NativeCredDelete([In] string targetName, [In] uint type, [In] uint flags);

        [DllImport("advapi32.dll", EntryPoint = "CredFree", SetLastError = false)]
        private static extern void NativeCredFree([In] IntPtr buffer);

        public bool CredWrite(ref NativeCredential credential, uint flags)
        {
            return NativeCredWrite(ref credential, flags);
        }

        public bool CredRead(string targetName, uint type, uint reservedFlag, out IntPtr credentialPtr)
        {
            return NativeCredRead(targetName, type, reservedFlag, out credentialPtr);
        }

        public bool CredDelete(string targetName, uint type, uint flags)
        {
            return NativeCredDelete(targetName, type, flags);
        }

        public void CredFree(IntPtr buffer)
        {
            NativeCredFree(buffer);
        }

        public int GetLastWin32Error()
        {
            return Marshal.GetLastWin32Error();
        }
    }

    internal sealed class FakeNativeCredentialApi : INativeCredentialApi
    {
        public delegate bool WriteDelegate(ref NativeCredential credential, uint flags);
        public delegate bool ReadDelegate(string targetName, uint type, uint reservedFlag, out IntPtr credentialPtr);
        public delegate bool DeleteDelegate(string targetName, uint type, uint flags);

        public WriteDelegate OnWrite;
        public ReadDelegate OnRead;
        public DeleteDelegate OnDelete;
        public Action<IntPtr> OnFree;
        public int LastError;

        public bool CredWrite(ref NativeCredential credential, uint flags)
        {
            if (OnWrite != null) return OnWrite(ref credential, flags);
            return true;
        }

        public bool CredRead(string targetName, uint type, uint reservedFlag, out IntPtr credentialPtr)
        {
            if (OnRead != null) return OnRead(targetName, type, reservedFlag, out credentialPtr);
            credentialPtr = IntPtr.Zero;
            return false;
        }

        public bool CredDelete(string targetName, uint type, uint flags)
        {
            if (OnDelete != null) return OnDelete(targetName, type, flags);
            return true;
        }

        public void CredFree(IntPtr buffer)
        {
            if (OnFree != null) OnFree(buffer);
            else if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer);
        }

        public int GetLastWin32Error()
        {
            return LastError;
        }
    }

    public sealed class SecureCredentialManager
    {
        public const string ProductionPrefix = "InvestorIntelligence/V1/";
        public const string SyntheticPrefixBase = "InvestorIntelligence/Synthetic/";

        public const uint CRED_TYPE_GENERIC = 1;
        public const uint CRED_PERSIST_LOCAL_MACHINE = 2;

        private const int ERROR_NOT_FOUND = 1168;
        private const int ERROR_ACCESS_DENIED = 5;

        public const int MaxCredentialBlobBytes = 2560;

        public static readonly string[] AllowedServiceIds = new string[]
        {
            "LINE_CHANNEL_ACCESS_TOKEN",
            "LINE_CHANNEL_SECRET",
            "CLOUDFLARE_API_TOKEN",
            "GITHUB_TOKEN",
            "ALPHAVANTAGE_API_KEY"
        };

        private static readonly HashSet<string> AllowedServicesSet =
            new HashSet<string>(AllowedServiceIds, StringComparer.Ordinal);

        private readonly string prefix;
        private readonly INativeCredentialApi native;

        public SecureCredentialManager() : this(ProductionPrefix, new Advapi32NativeCredentialApi())
        {
        }

        internal SecureCredentialManager(string prefix, INativeCredentialApi native)
        {
            if (string.IsNullOrEmpty(prefix))
                throw new ArgumentNullException("prefix");
            this.prefix = prefix;
            this.native = native ?? new Advapi32NativeCredentialApi();
        }

        public static bool IsAllowedService(string serviceId)
        {
            return !string.IsNullOrEmpty(serviceId) && AllowedServicesSet.Contains(serviceId);
        }

        public static void ValidateServiceId(string serviceId)
        {
            if (!IsAllowedService(serviceId))
                throw new ArgumentException("UNKNOWN_SERVICE_ID", "serviceId");
        }

        public static void ValidateSecret(string secret)
        {
            if (secret == null)
                throw new ArgumentNullException("secret", "CREDENTIAL_SECRET_REQUIRED");
            if (secret.Length == 0)
                throw new ArgumentException("CREDENTIAL_SECRET_EMPTY", "secret");
            int byteCount = Encoding.Unicode.GetByteCount(secret);
            if (byteCount > MaxCredentialBlobBytes)
                throw new ArgumentException("CREDENTIAL_SECRET_TOO_LARGE", "secret");
            for (int i = 0; i < secret.Length; i++)
            {
                char c = secret[i];
                if (c == '\0' || c == '\r' || c == '\n')
                    throw new ArgumentException("CREDENTIAL_SECRET_FORBIDDEN_CHARACTERS", "secret");
            }
        }

        private string GetTargetName(string serviceId)
        {
            ValidateServiceId(serviceId);
            return this.prefix + serviceId;
        }

        private static void ZeroNativeMemory(IntPtr ptr, int size)
        {
            if (ptr == IntPtr.Zero || size <= 0) return;
            for (int i = 0; i < size; i++)
            {
                Marshal.WriteByte(ptr, i, 0);
            }
        }

        private static void ZeroNativeBlob(IntPtr credentialPtr)
        {
            if (credentialPtr == IntPtr.Zero) return;
            try
            {
                int sizeOffset = IntPtr.Size == 8 ? 32 : 24;
                int blobOffset = IntPtr.Size == 8 ? 40 : 28;
                int size = Marshal.ReadInt32(credentialPtr, sizeOffset);
                IntPtr blob = Marshal.ReadIntPtr(credentialPtr, blobOffset);
                if (blob != IntPtr.Zero && size > 0 && size <= MaxCredentialBlobBytes)
                {
                    ZeroNativeMemory(blob, size);
                }
            }
            catch
            {
            }
        }

        public bool ContainsCredential(string serviceId)
        {
            ValidateServiceId(serviceId);
            string target = GetTargetName(serviceId);
            IntPtr credentialPtr = IntPtr.Zero;
            bool success = native.CredRead(target, CRED_TYPE_GENERIC, 0, out credentialPtr);
            if (!success)
            {
                int error = native.GetLastWin32Error();
                if (error == ERROR_NOT_FOUND)
                {
                    return false;
                }
                throw new InvalidOperationException("CREDENTIAL_STORE_UNAVAILABLE");
            }

            try
            {
                int typeOffset = 4;
                int sizeOffset = IntPtr.Size == 8 ? 32 : 24;
                int blobOffset = IntPtr.Size == 8 ? 40 : 28;

                uint type = (uint)Marshal.ReadInt32(credentialPtr, typeOffset);
                int size = Marshal.ReadInt32(credentialPtr, sizeOffset);
                IntPtr blob = Marshal.ReadIntPtr(credentialPtr, blobOffset);

                if (type != CRED_TYPE_GENERIC || size <= 0 || size > MaxCredentialBlobBytes || (size % 2) != 0 || blob == IntPtr.Zero)
                {
                    throw new InvalidOperationException("CREDENTIAL_STORE_CORRUPT");
                }
                return true;
            }
            finally
            {
                ZeroNativeBlob(credentialPtr);
                native.CredFree(credentialPtr);
            }
        }

        public void WithSecret(string serviceId, Action<char[]> callback)
        {
            if (callback == null)
                throw new ArgumentNullException("callback");
            WithSecret(serviceId, delegate(char[] chars) {
                callback(chars);
                return 0;
            });
        }

        public T WithSecret<T>(string serviceId, Func<char[], T> callback)
        {
            if (callback == null)
                throw new ArgumentNullException("callback");
            ValidateServiceId(serviceId);
            string target = GetTargetName(serviceId);
            IntPtr credentialPtr = IntPtr.Zero;
            bool success = native.CredRead(target, CRED_TYPE_GENERIC, 0, out credentialPtr);
            if (!success)
            {
                int error = native.GetLastWin32Error();
                if (error == ERROR_NOT_FOUND)
                {
                    throw new KeyNotFoundException("CREDENTIAL_NOT_FOUND");
                }
                throw new InvalidOperationException("CREDENTIAL_STORE_UNAVAILABLE");
            }

            try
            {
                int typeOffset = 4;
                int sizeOffset = IntPtr.Size == 8 ? 32 : 24;
                int blobOffset = IntPtr.Size == 8 ? 40 : 28;

                uint type = (uint)Marshal.ReadInt32(credentialPtr, typeOffset);
                int size = Marshal.ReadInt32(credentialPtr, sizeOffset);
                IntPtr blob = Marshal.ReadIntPtr(credentialPtr, blobOffset);

                if (type != CRED_TYPE_GENERIC || size <= 0 || size > MaxCredentialBlobBytes || (size % 2) != 0 || blob == IntPtr.Zero)
                {
                    throw new InvalidOperationException("CREDENTIAL_STORE_CORRUPT");
                }

                byte[] managedBytes = new byte[size];
                try
                {
                    Marshal.Copy(blob, managedBytes, 0, size);
                    char[] chars = Encoding.Unicode.GetChars(managedBytes);
                    try
                    {
                        // Managed memory / OS limits: In the .NET CLR and Windows OS, strings or memory pages
                        // may be moved by the GC or swapped to the paging file by the OS.
                        // Array.Clear zeros the temporary char[] buffer, but cannot guarantee that
                        // previous memory locations or CPU registers were not paged or relocated
                        // before zeroing. This callback model provides bounded-lifetime exposure,
                        // not a false zero-copy or hardware-tamper-proof guarantee.
                        Array.Clear(managedBytes, 0, managedBytes.Length);
                        return callback(chars);
                    }
                    finally
                    {
                        Array.Clear(chars, 0, chars.Length);
                    }
                }
                finally
                {
                    Array.Clear(managedBytes, 0, managedBytes.Length);
                }
            }
            finally
            {
                ZeroNativeBlob(credentialPtr);
                native.CredFree(credentialPtr);
            }
        }

        public void SetSecret(string serviceId, string secret)
        {
            ValidateServiceId(serviceId);
            ValidateSecret(secret);
            string target = GetTargetName(serviceId);

            byte[] bytes = Encoding.Unicode.GetBytes(secret);
            IntPtr unmanagedBlob = IntPtr.Zero;
            try
            {
                unmanagedBlob = Marshal.AllocHGlobal(bytes.Length);
                Marshal.Copy(bytes, 0, unmanagedBlob, bytes.Length);
                Array.Clear(bytes, 0, bytes.Length);

                var cred = new NativeCredential();
                cred.Flags = 0;
                cred.Type = CRED_TYPE_GENERIC;
                cred.TargetName = target;
                cred.Comment = IntPtr.Zero;
                cred.LastWrittenLow = 0;
                cred.LastWrittenHigh = 0;
                cred.CredentialBlobSize = (uint)bytes.Length;
                cred.CredentialBlob = unmanagedBlob;
                cred.Persist = CRED_PERSIST_LOCAL_MACHINE;
                cred.AttributeCount = 0;
                cred.Attributes = IntPtr.Zero;
                cred.TargetAlias = IntPtr.Zero;
                cred.UserName = IntPtr.Zero;

                bool success = native.CredWrite(ref cred, 0);
                if (!success)
                {
                    throw new InvalidOperationException("CREDENTIAL_STORE_WRITE_FAILED");
                }
            }
            finally
            {
                Array.Clear(bytes, 0, bytes.Length);
                if (unmanagedBlob != IntPtr.Zero)
                {
                    ZeroNativeMemory(unmanagedBlob, bytes.Length);
                    Marshal.FreeHGlobal(unmanagedBlob);
                }
            }
        }

        public bool DeleteCredential(string serviceId)
        {
            ValidateServiceId(serviceId);
            string target = GetTargetName(serviceId);
            bool success = native.CredDelete(target, CRED_TYPE_GENERIC, 0);
            if (!success)
            {
                int error = native.GetLastWin32Error();
                if (error == ERROR_NOT_FOUND)
                {
                    return false;
                }
                throw new InvalidOperationException("CREDENTIAL_STORE_DELETE_FAILED");
            }
            return true;
        }

        internal static SecureCredentialManager CreateSyntheticTestStore(string testGuid, INativeCredentialApi native = null)
        {
            Guid parsed;
            if (string.IsNullOrEmpty(testGuid) || !Guid.TryParse(testGuid, out parsed))
                throw new ArgumentException("INVALID_TEST_GUID", "testGuid");
            return new SecureCredentialManager(SyntheticPrefixBase + parsed.ToString("D") + "/", native);
        }

        private static string GenerateRandomSecret(int length)
        {
            const string chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_~.";
            byte[] randomBytes = new byte[length];
            using (var rng = new RNGCryptoServiceProvider())
            {
                rng.GetBytes(randomBytes);
            }
            char[] secretChars = new char[length];
            for (int i = 0; i < length; i++)
            {
                secretChars[i] = chars[randomBytes[i] % chars.Length];
            }
            Array.Clear(randomBytes, 0, randomBytes.Length);
            return new string(secretChars);
        }

        public static int RunSelfTest()
        {
            // Part 1: Input Rejection Checks (RAM-only)
            string fakeGuid = Guid.NewGuid().ToString("D");
            FakeNativeCredentialApi fakeApi = new FakeNativeCredentialApi();
            SecureCredentialManager testStore = CreateSyntheticTestStore(fakeGuid, fakeApi);
            const string validService = "LINE_CHANNEL_ACCESS_TOKEN";

            // 1. Unknown service ID rejection
            try { testStore.SetSecret("UNKNOWN_SERVICE", "valid_secret"); return 101; } catch (ArgumentException) { }
            try { testStore.ContainsCredential("UNKNOWN_SERVICE"); return 102; } catch (ArgumentException) { }
            try { testStore.DeleteCredential("UNKNOWN_SERVICE"); return 103; } catch (ArgumentException) { }
            try { testStore.WithSecret("UNKNOWN_SERVICE", delegate(char[] c) { }); return 104; } catch (ArgumentException) { }

            // 2. Null or empty secret rejection
            try { testStore.SetSecret(validService, null); return 105; } catch (ArgumentNullException) { }
            try { testStore.SetSecret(validService, ""); return 106; } catch (ArgumentException) { }

            // 3. Forbidden characters rejection (\0, \r, \n)
            try { testStore.SetSecret(validService, "abc\0def"); return 107; } catch (ArgumentException) { }
            try { testStore.SetSecret(validService, "abc\rdef"); return 108; } catch (ArgumentException) { }
            try { testStore.SetSecret(validService, "abc\ndef"); return 109; } catch (ArgumentException) { }

            // 4. Oversized secret rejection (> 2560 UTF16 bytes = 1281 chars)
            string oversized = new string('x', 1281);
            try { testStore.SetSecret(validService, oversized); return 110; } catch (ArgumentException) { }

            // Exact boundary secret (1280 chars = 2560 bytes) must pass validation
            string boundarySecret = new string('x', 1280);
            bool fakeWriteCalled = false;
            fakeApi.OnWrite = delegate(ref NativeCredential cred, uint flags) {
                fakeWriteCalled = true;
                return true;
            };
            try { testStore.SetSecret(validService, boundarySecret); }
            catch { return 111; }
            if (!fakeWriteCalled) return 112;

            // Part 2: Missing vs Error / Corrupt handling via narrow fake native seam
            // 1. ERROR_ACCESS_DENIED (5) on read: fail closed
            fakeApi.LastError = ERROR_ACCESS_DENIED;
            fakeApi.OnRead = delegate(string t, uint tp, uint f, out IntPtr ptr) { ptr = IntPtr.Zero; return false; };
            try { testStore.ContainsCredential(validService); return 120; } catch (InvalidOperationException) { }
            try { testStore.WithSecret(validService, delegate(char[] c) { }); return 121; } catch (InvalidOperationException) { }

            // 2. ERROR_NOT_FOUND (1168) on read: distinct missing
            fakeApi.LastError = ERROR_NOT_FOUND;
            try {
                if (testStore.ContainsCredential(validService)) return 122;
            } catch { return 122; }

            bool keyNotFoundThrown = false;
            try { testStore.WithSecret(validService, delegate(char[] c) { }); }
            catch (KeyNotFoundException) { keyNotFoundThrown = true; }
            catch { return 123; }
            if (!keyNotFoundThrown) return 123;

            // 3. Corrupt credential type on read (type = 99): fail closed & free buffer
            int fakeStructSize = IntPtr.Size == 8 ? 80 : 52;
            IntPtr corruptTypeBuf = Marshal.AllocHGlobal(fakeStructSize);
            ZeroNativeMemory(corruptTypeBuf, fakeStructSize);
            Marshal.WriteInt32(corruptTypeBuf, 4, 99); // Type != CRED_TYPE_GENERIC
            bool corruptFreed = false;
            fakeApi.OnRead = delegate(string t, uint tp, uint f, out IntPtr ptr) { ptr = corruptTypeBuf; return true; };
            fakeApi.OnFree = delegate(IntPtr b) { corruptFreed = true; Marshal.FreeHGlobal(b); };
            try { testStore.ContainsCredential(validService); return 124; } catch (InvalidOperationException) { }
            if (!corruptFreed) return 125;

            // 4. Corrupt blob size on read (odd bytes = 5): fail closed & free buffer
            IntPtr oddBlob = Marshal.AllocHGlobal(5);
            IntPtr corruptBlobBuf = Marshal.AllocHGlobal(fakeStructSize);
            ZeroNativeMemory(corruptBlobBuf, fakeStructSize);
            Marshal.WriteInt32(corruptBlobBuf, 4, (int)CRED_TYPE_GENERIC);
            int sizeOff = IntPtr.Size == 8 ? 32 : 24;
            int blobOff = IntPtr.Size == 8 ? 40 : 28;
            Marshal.WriteInt32(corruptBlobBuf, sizeOff, 5); // odd size
            Marshal.WriteIntPtr(corruptBlobBuf, blobOff, oddBlob);
            bool blobBufFreed = false;
            fakeApi.OnRead = delegate(string t, uint tp, uint f, out IntPtr ptr) { ptr = corruptBlobBuf; return true; };
            fakeApi.OnFree = delegate(IntPtr b) {
                blobBufFreed = true;
                Marshal.FreeHGlobal(oddBlob);
                Marshal.FreeHGlobal(b);
            };
            try { testStore.WithSecret(validService, delegate(char[] c) { }); return 126; } catch (InvalidOperationException) { }
            if (!blobBufFreed) return 127;

            // 5. Native write failure: fail closed
            fakeApi.LastError = ERROR_ACCESS_DENIED;
            fakeApi.OnWrite = delegate(ref NativeCredential cred, uint flags) { return false; };
            try { testStore.SetSecret(validService, "some_secret"); return 128; } catch (InvalidOperationException) { }

            // 6. Native delete failure: fail closed
            fakeApi.LastError = ERROR_ACCESS_DENIED;
            fakeApi.OnDelete = delegate(string t, uint tp, uint flags) { return false; };
            try { testStore.DeleteCredential(validService); return 129; } catch (InvalidOperationException) { }

            // Part 3: Authorized Real Native Windows Credential Manager Test
            // Separate unique namespace: InvestorIntelligence/Synthetic/<nativeTestGuid>/
            string nativeTestGuid = Guid.NewGuid().ToString("D");
            SecureCredentialManager nativeStore = CreateSyntheticTestStore(nativeTestGuid);
            try
            {
                // 1. Initial existence check: must be missing
                try {
                    if (nativeStore.ContainsCredential(validService)) return 131;
                } catch { return 131; }

                bool initialNotFound = false;
                try { nativeStore.WithSecret(validService, delegate(char[] c) { }); }
                catch (KeyNotFoundException) { initialNotFound = true; }
                catch { return 132; }
                if (!initialNotFound) return 132;

                // 2. Generate random synthetic secret 1 in RAM only (e.g. 40 chars)
                string secret1 = GenerateRandomSecret(40);
                nativeStore.SetSecret(validService, secret1);

                // 3. Existence check after write: must be present
                if (!nativeStore.ContainsCredential(validService)) return 133;

                // 4. Read secret 1 and verify exact match
                bool secret1Matched = false;
                nativeStore.WithSecret(validService, delegate(char[] chars) {
                    if (chars != null && chars.Length == secret1.Length)
                    {
                        secret1Matched = true;
                        for (int i = 0; i < chars.Length; i++)
                        {
                            if (chars[i] != secret1[i]) { secret1Matched = false; break; }
                        }
                    }
                });
                if (!secret1Matched) return 134;

                // 5. Callback error cleanup: callback throws exception, verify buffer zeroed in finally
                bool callbackThrew = false;
                char[] capturedChars = null;
                try
                {
                    nativeStore.WithSecret(validService, delegate(char[] chars) {
                        capturedChars = chars;
                        throw new ApplicationException("TEST_CALLBACK_CLEANUP_EXCEPTION");
                    });
                }
                catch (ApplicationException ex)
                {
                    if (ex.Message == "TEST_CALLBACK_CLEANUP_EXCEPTION") callbackThrew = true;
                }
                if (!callbackThrew) return 135;
                if (capturedChars == null || capturedChars.Length != secret1.Length) return 135;
                for (int i = 0; i < capturedChars.Length; i++)
                {
                    if (capturedChars[i] != '\0') return 135;
                }

                // 6. Replacement test: write secret 2 and verify match
                string secret2 = GenerateRandomSecret(56);
                nativeStore.SetSecret(validService, secret2);

                bool secret2Matched = false;
                nativeStore.WithSecret(validService, delegate(char[] chars) {
                    if (chars != null && chars.Length == secret2.Length)
                    {
                        secret2Matched = true;
                        for (int i = 0; i < chars.Length; i++)
                        {
                            if (chars[i] != secret2[i]) { secret2Matched = false; break; }
                        }
                    }
                });
                if (!secret2Matched) return 136;

                // 7. Verify no silent trim: spaces are preserved
                string secretWithSpaces = "  " + GenerateRandomSecret(20) + "  ";
                nativeStore.SetSecret(validService, secretWithSpaces);
                bool spacesPreserved = false;
                nativeStore.WithSecret(validService, delegate(char[] chars) {
                    if (chars != null && chars.Length == secretWithSpaces.Length)
                    {
                        spacesPreserved = true;
                        for (int i = 0; i < chars.Length; i++)
                        {
                            if (chars[i] != secretWithSpaces[i]) { spacesPreserved = false; break; }
                        }
                    }
                });
                if (!spacesPreserved) return 137;

                // 8. Delete credential
                bool deleted = nativeStore.DeleteCredential(validService);
                if (!deleted) return 138;

                // 9. Missing after delete
                if (nativeStore.ContainsCredential(validService)) return 139;

                // 10. Second delete returns false
                bool secondDelete = nativeStore.DeleteCredential(validService);
                if (secondDelete) return 140;
            }
            finally
            {
                // ALWAYS delete only its OWN unique target in finally! Never touch production prefix!
                try
                {
                    nativeStore.DeleteCredential(validService);
                }
                catch
                {
                }
            }

            Console.WriteLine("INVESTOR_INTELLIGENCE_SECURE_STORE_SELF_TEST=PASS");
            return 0;
        }

        public override string ToString()
        {
            return "InvestorIntelligence.SecureCredentialManager[" + this.prefix + "]";
        }
    }
}
