// Test-only: explicit authorized child, own newly-created fixture, SACL reads only.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;

public static class V213SaclPrivilegeProbe {
    public sealed class Result {
        public string status = "ERROR", operation_status = "NOT_ATTEMPTED";
        public bool assigned, enabled_before, enable_attempted, enabled_during, read_attempted, restore_attempted;
        public bool? privileges_restored, other_privileges_unchanged, sacl_present, sacl_null, two_reads_equal, fixture_bytes_unchanged;
        public uint enable_error, read_error, restore_error;
        public int child_pid = System.Diagnostics.Process.GetCurrentProcess().Id;
        public bool release_qualified = false, raw_security_data_retained = false;
    }
    sealed class ReadResult {
        public uint Code;
        public bool Present, Null, Equal;
    }
    interface IContext {
        ulong Selected { get; }
        Dictionary<ulong,uint> Snapshot();
        uint SetSelected(uint attributes);
        ReadResult Read();
    }
    static bool Same(Dictionary<ulong,uint> a, Dictionary<ulong,uint> b, ulong? except) {
        foreach (var pair in a) {
            if (except.HasValue && pair.Key == except.Value) continue;
            uint v; if (!b.TryGetValue(pair.Key, out v) || v != pair.Value) return false;
        }
        foreach (var pair in b) {
            if (except.HasValue && pair.Key == except.Value) continue;
            if (!a.ContainsKey(pair.Key)) return false;
        }
        return true;
    }
    static Result Run(IContext api) {
        var r = new Result();
        var before = api.Snapshot();
        uint original;
        r.assigned = before.TryGetValue(api.Selected, out original) && (original & 4) == 0;
        r.enabled_before = r.assigned && (original & 2) != 0;
        if (!r.assigned) {
            r.status = r.operation_status = "BLOCKED_PRIVILEGE_NOT_ASSIGNED";
            r.privileges_restored = Same(before, api.Snapshot(), null);
            r.other_privileges_unchanged = r.privileges_restored;
            return r; // Do not call AdjustTokenPrivileges for an absent privilege.
        }
        try {
            if (!r.enabled_before) {
                r.enable_attempted = true;
                r.enable_error = api.SetSelected(original | 2);
                if (r.enable_error != 0) { r.operation_status = "BLOCKED_ENABLE"; return r; }
            }
            var during = api.Snapshot(); uint attributes;
            r.enabled_during = during.TryGetValue(api.Selected, out attributes) && (attributes & 2) != 0;
            if (!r.enabled_during || !Same(before, during, api.Selected)) {
                r.operation_status = "UNEXPECTED_PRIVILEGE_STATE"; return r;
            }
            r.read_attempted = true;
            var read = api.Read(); r.read_error = read.Code;
            if (read.Code != 0) { r.operation_status = "BLOCKED_READ"; return r; }
            r.sacl_present = read.Present; r.sacl_null = read.Null; r.two_reads_equal = read.Equal;
            r.operation_status = read.Equal ? "PASS" : "READ_CHANGED";
            return r;
        }
        catch { r.operation_status = "EXCEPTION"; return r; }
        finally {
            try {
                if (r.enable_attempted) {
                    r.restore_attempted = true;
                    r.restore_error = api.SetSelected(original);
                }
                var after = api.Snapshot();
                r.privileges_restored = r.restore_error == 0 && Same(before, after, null);
                r.other_privileges_unchanged = Same(before, after, api.Selected);
            }
            catch { r.privileges_restored = false; r.other_privileges_unchanged = null; }
            r.status = r.privileges_restored == true ? r.operation_status : "RESTORE_FAILED";
        }
    }

    [StructLayout(LayoutKind.Sequential)] struct Luid { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential)] struct OnePrivilege { public uint Count; public Luid Id; public uint Attributes; }
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentThread();
    [DllImport("kernel32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll")] static extern void SetLastError(uint code);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr address);
    [DllImport("advapi32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr handle);
    [DllImport("advapi32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    static extern bool OpenThreadToken(IntPtr thread, uint access, [MarshalAs(UnmanagedType.Bool)] bool asSelf, out IntPtr handle);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    static extern bool LookupPrivilegeValueW(string system, string name, out Luid id);
    [DllImport("advapi32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    static extern bool GetTokenInformation(IntPtr handle, int kind, IntPtr buffer, uint size, out uint required);
    [DllImport("advapi32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    static extern bool AdjustTokenPrivileges(IntPtr handle, [MarshalAs(UnmanagedType.Bool)] bool disableAll,
        ref OnePrivilege state, uint size, IntPtr previous, IntPtr required);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, ExactSpelling=true)]
    static extern uint GetNamedSecurityInfoW(string name, uint type, uint info, out IntPtr owner,
        out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    static extern bool GetSecurityDescriptorControl(IntPtr descriptor, out ushort control, out uint revision);
    static ulong Key(Luid id) { return ((ulong)(uint)id.High << 32) | id.Low; }

    sealed class NativeContext : IContext, IDisposable {
        IntPtr accessHandle; Luid selected; readonly string fixture;
        public ulong Selected { get { return Key(selected); } }
        public NativeContext(string path) {
            fixture = path;
            IntPtr threadHandle;
            if (OpenThreadToken(GetCurrentThread(), 8, true, out threadHandle)) {
                CloseHandle(threadHandle); throw new InvalidOperationException("IMPERSONATION_CONTEXT_REJECTED");
            }
            if (Marshal.GetLastWin32Error() != 1008) throw new InvalidOperationException("THREAD_CONTEXT_UNAVAILABLE");
            if (!LookupPrivilegeValueW(null, "SeSecurityPrivilege", out selected)) throw new InvalidOperationException("PRIVILEGE_LOOKUP_FAILED");
            // Current process ONLY; no other process handles, linked tokens, policy APIs or elevation.
            if (!OpenProcessToken(GetCurrentProcess(), 8 | 32, out accessHandle)) throw new InvalidOperationException("SELF_ACCESS_UNAVAILABLE");
        }
        public Dictionary<ulong,uint> Snapshot() {
            uint needed;
            GetTokenInformation(accessHandle, 3, IntPtr.Zero, 0, out needed);
            if (needed < 4 || needed > 65536) throw new InvalidOperationException("PRIVILEGE_BUFFER_BOUND");
            IntPtr data = Marshal.AllocHGlobal((int)needed);
            try {
                if (!GetTokenInformation(accessHandle, 3, data, needed, out needed)) throw new InvalidOperationException("PRIVILEGE_QUERY_FAILED");
                int count = Marshal.ReadInt32(data);
                if (count < 0 || count > 256 || 4 + count * 12 > needed) throw new InvalidOperationException("PRIVILEGE_COUNT_BOUND");
                var result = new Dictionary<ulong,uint>();
                for (int i = 0; i < count; i++) {
                    IntPtr p = IntPtr.Add(data, 4 + i * 12);
                    var id = (Luid)Marshal.PtrToStructure(p, typeof(Luid));
                    result.Add(Key(id), (uint)Marshal.ReadInt32(p, 8));
                }
                return result; // Internal only: never serialize privilege lists or handles.
            }
            finally { Marshal.FreeHGlobal(data); }
        }
        public uint SetSelected(uint attributes) {
            var state = new OnePrivilege { Count = 1, Id = selected, Attributes = attributes };
            SetLastError(0);
            bool ok = AdjustTokenPrivileges(accessHandle, false, ref state, 0, IntPtr.Zero, IntPtr.Zero);
            uint error = (uint)Marshal.GetLastWin32Error();
            // A successful BOOL with ERROR_NOT_ALL_ASSIGNED (1300) is NOT success.
            return !ok && error == 0 ? 13u : error;
        }
        sealed class Sacl { public uint Code; public ushort Control; public byte[] Bytes; }
        Sacl ReadOnce() {
            IntPtr o, g, d, s, descriptor;
            var result = new Sacl();
            result.Code = GetNamedSecurityInfoW(fixture, 1, 8, out o, out g, out d, out s, out descriptor);
            try {
                if (result.Code != 0) return result;
                ushort control; uint revision;
                if (!GetSecurityDescriptorControl(descriptor, out control, out revision)) {
                    result.Code = (uint)Marshal.GetLastWin32Error(); if (result.Code == 0) result.Code = 13; return result;
                }
                result.Control = (ushort)(control & 0x2a30); // Only SACL control flags.
                if (s != IntPtr.Zero) {
                    int size = (ushort)Marshal.ReadInt16(s, 2);
                    if (size < 8) { result.Code = 13; return result; }
                    result.Bytes = new byte[size]; Marshal.Copy(s, result.Bytes, 0, size);
                }
                return result;
            }
            finally { if (descriptor != IntPtr.Zero) LocalFree(descriptor); }
        }
        public ReadResult Read() {
            var first = ReadOnce(); if (first.Code != 0) return new ReadResult { Code = first.Code };
            var second = ReadOnce(); if (second.Code != 0) return new ReadResult { Code = second.Code };
            bool equal = first.Control == second.Control && (first.Bytes == null) == (second.Bytes == null);
            if (first.Bytes != null && second.Bytes != null) {
                equal &= first.Bytes.Length == second.Bytes.Length;
                if (equal) for (int i = 0; i < first.Bytes.Length; i++) equal &= first.Bytes[i] == second.Bytes[i];
            }
            return new ReadResult { Code = 0, Present = (first.Control & 16) != 0, Null = first.Bytes == null, Equal = equal };
        }
        public void Dispose() { if (accessHandle != IntPtr.Zero) { CloseHandle(accessHandle); accessHandle = IntPtr.Zero; } }
    }

    public static Result ReadNewFixture(string root) {
        string full = Path.GetFullPath(root);
        if (!Path.IsPathRooted(root) || root.StartsWith(@"\\", StringComparison.Ordinal) || full != root || root.Contains(".."))
            throw new InvalidOperationException("FIXTURE_PATH_REJECTED");
        var drive = new DriveInfo(Path.GetPathRoot(full));
        if (drive.DriveType != DriveType.Fixed || drive.DriveFormat != "NTFS") throw new InvalidOperationException("FIXTURE_LOCAL_NTFS_REQUIRED");
        for (var p = new DirectoryInfo(full); p != null; p = p.Parent) {
            if (!p.Exists || (p.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException("FIXTURE_REPARSE_REJECTED");
        }
        // Creation occurs BEFORE opening/adjusting the child privilege. Existing paths are never read.
        string target = Path.Combine(full, "sacl-read-target.bin");
        using (var file = new FileStream(target, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.Read)) {
            byte[] bytes = { 83, 65, 67, 76 }; file.Write(bytes, 0, bytes.Length); file.Flush(true);
            Result result;
            using (var api = new NativeContext(target)) { result = Run(api); }
            try {
                file.Position = 0; bool same = file.Length == bytes.Length;
                foreach (byte b in bytes) same &= file.ReadByte() == b;
                result.fixture_bytes_unchanged = same;
            }
            catch { result.fixture_bytes_unchanged = false; }
            if (result.fixture_bytes_unchanged != true && result.status == "PASS") result.status = "FIXTURE_CHANGED";
            return result;
        }
    }

    sealed class Fake : IContext {
        public readonly Dictionary<ulong,uint> State = new Dictionary<ulong,uint>();
        public ulong Selected { get { return 8; } }
        public int Calls, Reads; public bool ThrowRead, RestoreFails, OtherChanged; public uint EnableError, ReadError;
        public Dictionary<ulong,uint> Snapshot() { return new Dictionary<ulong,uint>(State); }
        public uint SetSelected(uint attrs) {
            Calls++;
            if (Calls == 1 && EnableError != 0) return EnableError;
            if (Calls == 2 && RestoreFails) return 5;
            State[8] = attrs; return 0;
        }
        public ReadResult Read() {
            Reads++; if (ThrowRead) throw new IOException("SYNTHETIC_PRIVATE_MUST_NOT_ESCAPE");
            if (OtherChanged) State[9] = 2;
            return new ReadResult { Code = ReadError, Equal = true, Null = true, Present = false };
        }
    }
    public static string[] SelfTest() {
        var names = new List<string>();
        foreach (string name in new[] { "missing", "already-enabled", "restore-success", "read-failure", "read-exception", "not-all-assigned", "restore-failure", "other-privilege-change" }) {
            var f = new Fake(); f.State[9] = 0;
            if (name != "missing") f.State[8] = name == "already-enabled" ? 2u : 0u;
            f.ThrowRead = name == "read-exception"; f.ReadError = name == "read-failure" ? 5u : 0u;
            f.EnableError = name == "not-all-assigned" ? 1300u : 0u;
            f.RestoreFails = name == "restore-failure"; f.OtherChanged = name == "other-privilege-change";
            var r = Run(f);
            string wanted = name == "missing" ? "BLOCKED_PRIVILEGE_NOT_ASSIGNED" :
                name == "read-failure" ? "BLOCKED_READ" : name == "read-exception" ? "EXCEPTION" :
                name == "not-all-assigned" ? "BLOCKED_ENABLE" :
                (name == "restore-failure" || name == "other-privilege-change") ? "RESTORE_FAILED" : "PASS";
            int calls = name == "missing" || name == "already-enabled" ? 0 : 2;
            if (r.status != wanted || f.Calls != calls || (name == "missing" && f.Reads != 0) ||
                (wanted != "RESTORE_FAILED" && r.privileges_restored != true) ||
                (wanted == "RESTORE_FAILED" && r.privileges_restored != false))
                throw new InvalidOperationException("SELF_TEST_ORACLE_FAILED");
            names.Add(name);
        }
        return names.ToArray(); // No native context is constructed by these tests.
    }
}
