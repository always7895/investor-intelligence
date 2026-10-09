# F02D source-only protected private-pipe backend. Default disabled: no registry,
# authority/native access, process, timer task, model, environment or install action.
# Parent carries intent only. Real P2 tokens/snapshots/live witnesses NEVER leave
# the protected Python owner. No timeout kill/replacement/ACK/close workaround.
Set-StrictMode -Version Latest
$script:RetainedGuidanceHosts = [Collections.Generic.List[object]]::new()
$script:RetainedGuidanceOrigins = [Collections.Generic.List[object]]::new()
$script:ObservedGuidanceProcesses = [Collections.Generic.List[object]]::new()
$script:GuidanceLifetimeEvent = [Threading.ManualResetEvent]::new($false) # never signalled
$script:GuidanceProtocol = 'guidance-private-host-v1'
$script:RetainedGuidanceStages = [Collections.Generic.List[object]]::new()

function _GuidanceJson([string]$Text, [int]$Limit = 16384) {
    if ([Text.Encoding]::UTF8.GetByteCount($Text) -gt $Limit) { throw 'GUIDANCE_FRAME_BOUND' }
    $doc = [Text.Json.JsonDocument]::Parse($Text, [Text.Json.JsonDocumentOptions]@{ MaxDepth=32 })
    function Visit($Element, [int]$Depth) {
        if ($Depth -gt 32) { throw 'GUIDANCE_FRAME_BOUND' }
        if ($Element.ValueKind -eq [Text.Json.JsonValueKind]::Object) {
            $keys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
            foreach ($p in $Element.EnumerateObject()) {
                if (-not $keys.Add($p.Name) -or $keys.Count -gt 8192) { throw 'GUIDANCE_FRAME_DUPLICATE' }
                Visit $p.Value ($Depth + 1)
            }
        } elseif ($Element.ValueKind -eq [Text.Json.JsonValueKind]::Array) {
            $count = 0
            foreach ($v in $Element.EnumerateArray()) {
                $count++
                if ($count -gt 8192) { throw 'GUIDANCE_FRAME_BOUND' }
                Visit $v ($Depth + 1)
            }
        } elseif ($Element.ValueKind -eq [Text.Json.JsonValueKind]::Number) {
            $n = $Element.GetDouble()
            if ([double]::IsNaN($n) -or [double]::IsInfinity($n)) { throw 'GUIDANCE_FRAME_NONFINITE' }
        }
    }
    try { Visit $doc.RootElement 0 } finally { $doc.Dispose() }
    return ConvertFrom-Json -InputObject $Text -AsHashtable -Depth 32
}

function _GuidanceNativeDeclarations {
    if ('GuidanceParentOrigin' -as [type]) { return }
    # SOURCE declarations only in this implementation phase. Future invocation
    # requires actual explicit opt-in, PS7.4 and protected machine prerequisites.
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;
public static class GuidanceParentOrigin {
    public static async Task<string> ReadFrame(StreamReader reader) {
        char[] chunk=new char[1]; StringBuilder text=new StringBuilder(1024);
        while(true) {
            int got=await reader.ReadAsync(chunk,0,1).ConfigureAwait(false);
            if(got==0) return text.Length==0 ? null : throw new InvalidOperationException("GUIDANCE_EOF_UNKNOWN");
            if(chunk[0]=='\n') return text.ToString();
            if(text.Length>=16384) throw new InvalidOperationException("GUIDANCE_FRAME_BOUND");
            text.Append(chunk[0]);
        }
    }
    public static async Task DrainSafeDiagnostics(StreamReader reader) {
        char[] chunk=new char[128]; int total=0;
        while(true) {
            int got=await reader.ReadAsync(chunk,0,chunk.Length).ConfigureAwait(false);
            if(got==0) return;
            total+=got;
            if(total>4096) throw new InvalidOperationException("GUIDANCE_DIAGNOSTIC_BOUND");
            // Contents deliberately discarded, NEVER returned/logged/persisted.
        }
    }
    [StructLayout(LayoutKind.Sequential)] struct Standard {
        public long AllocationSize, EndOfFile;
        public uint NumberOfLinks;
        public byte DeletePending, Directory;
    }
    [StructLayout(LayoutKind.Sequential)] struct Tags { public uint Attributes, ReparseTag; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateFileW(string p, uint a, uint s, IntPtr sec, uint d, uint f, IntPtr t);
    [DllImport("kernel32.dll", EntryPoint="GetFileInformationByHandleEx", SetLastError=true)]
    static extern bool GetStandard(IntPtr h, int cls, out Standard v, uint len);
    [DllImport("kernel32.dll", EntryPoint="GetFileInformationByHandleEx", SetLastError=true)]
    static extern bool GetTags(IntPtr h, int cls, out Tags v, uint len);
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool CloseHandle(IntPtr h);
    [DllImport("advapi32.dll")] public static extern int RegCloseKey(IntPtr h);
    [DllImport("advapi32.dll")] static extern uint GetSecurityInfo(IntPtr h, int kind, uint requested,
        out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr sd);
    [DllImport("advapi32.dll")] static extern uint GetSecurityDescriptorLength(IntPtr sd);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
    // Public DATA custody only; these objects never create a P1/P2 witness.
    public sealed class PublicNativeRequest {
        public IntPtr Parent,Text,Name,Attributes,Io,HandleSlot,Buffer,Handle;
        public bool Submitted,Terminal=true,Opened,CloseAttempted,CloseConfirmed;
    }
    public sealed class PublicLeaf {
        public IntPtr Handle; public long Length,Cap; public bool Fresh;
    }
    public sealed class PublicManagedIo {
        public SafeFileHandle Alias; public FileStream Stream; public SHA256 Digest; public byte[] Bytes;
        public bool Submitted,Settled,DisposeAttempted,Disposed;
    }
    public sealed class PublicStageOwner {
        public readonly System.Collections.Generic.List<PublicManagedIo> ManagedIo=
            new System.Collections.Generic.List<PublicManagedIo>(1);
        public readonly System.Collections.Generic.List<PublicNativeRequest> Requests=
            new System.Collections.Generic.List<PublicNativeRequest>(64);
        public readonly System.Collections.Generic.Dictionary<string,PublicLeaf> Leaves=
            new System.Collections.Generic.Dictionary<string,PublicLeaf>(32,StringComparer.Ordinal);
        public bool Submission,CloseAttempted,Closed,Unknown,InventoryStarted;
        public long AdmittedBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct UnicodeName { public ushort Length,MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)] struct ObjectAttributes {
        public uint Length; public IntPtr RootDirectory,ObjectName; public uint Attributes;
        public IntPtr SecurityDescriptor,SecurityQualityOfService;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoStatus { public IntPtr Status; public UIntPtr Information; }
    // All submitted arguments/results are actual owner-rooted unmanaged storage,
    // never stack-local out/ref marshalling. NT BOOLEAN is ONE byte, not Win32 BOOL.
    [DllImport("ntdll.dll", ExactSpelling=true)] static extern int NtCreateFile(IntPtr h,uint access,IntPtr oa,
        IntPtr ios,IntPtr allocation,uint attributes,uint share,uint disposition,uint options,IntPtr ea,uint ealen);
    [DllImport("ntdll.dll", ExactSpelling=true)] static extern int NtQueryDirectoryFile(IntPtr h,IntPtr ev,
        IntPtr apc,IntPtr context,IntPtr ios,IntPtr buffer,uint length,int informationClass,
        byte singleEntry,IntPtr name,byte restart);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint GetFileType(IntPtr h);
    static void PublicReady(PublicStageOwner owner) {
        if(owner.Unknown || owner.Submission || owner.CloseAttempted || owner.Closed || owner.ManagedIo.Count!=0)
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        foreach(var r in owner.Requests) if(!r.Terminal)
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
    }
    static void PublicHeld(PublicStageOwner owner,IntPtr h) {
        PublicReady(owner);
        foreach(var r in owner.Requests) if(r.Opened && r.Handle==h && !r.CloseAttempted) return;
        throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
    }
    static PublicNativeRequest PublicRequest(PublicStageOwner owner,IntPtr parent,string name,bool query) {
        PublicReady(owner);
        if(owner.Requests.Count>=64 || (name!=null && (name.Length<1 || name.Length>2048)))
            throw new InvalidOperationException("MACHINE_EVIDENCE_LIMIT");
        var r=new PublicNativeRequest {Parent=parent};
        owner.Requests.Add(r); // BEFORE first allocation, even allocation interruption retains the graph
        owner.Unknown=true;
        r.Io=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(IoStatus)));
        if(query) r.Buffer=Marshal.AllocHGlobal(4096);
        else {
            r.HandleSlot=Marshal.AllocHGlobal(IntPtr.Size); Marshal.WriteIntPtr(r.HandleSlot,IntPtr.Zero);
            r.Text=Marshal.StringToHGlobalUni(name);
            r.Name=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(UnicodeName)));
            Marshal.StructureToPtr(new UnicodeName {Length=checked((ushort)(name.Length*2)),
                MaximumLength=checked((ushort)(name.Length*2+2)),Buffer=r.Text},r.Name,false);
            r.Attributes=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(ObjectAttributes)));
            Marshal.StructureToPtr(new ObjectAttributes {Length=(uint)Marshal.SizeOf(typeof(ObjectAttributes)),
                RootDirectory=parent,ObjectName=r.Name,Attributes=0x40},r.Attributes,false);
        }
        owner.Unknown=false; return r; // no native submission yet; all allocated operands remain rooted
    }
    static void PublicSubmit(PublicStageOwner owner,PublicNativeRequest r) {
        PublicReady(owner);
        Marshal.StructureToPtr(new IoStatus {Status=new IntPtr(0x103),Information=UIntPtr.Zero},r.Io,false);
        r.Terminal=false; r.Submitted=true; owner.Submission=true; owner.Unknown=true;
    }
    static void PublicSettled(PublicStageOwner owner,PublicNativeRequest r) {
        r.Terminal=true; owner.Submission=false; owner.Unknown=false;
    }
    static IntPtr PublicOpen(PublicStageOwner owner,IntPtr parent,string name,bool directory,bool fresh,uint share) {
        if(parent!=IntPtr.Zero) PublicHeld(owner,parent);
        var r=PublicRequest(owner,parent,name,false);
        PublicSubmit(owner,r); // unknown is latched BEFORE the native call, including interrupted return
        int status=NtCreateFile(r.HandleSlot,directory ? 0x00100081u : (fresh ? 0xC0100080u : 0x00100081u),
            r.Attributes,r.Io,IntPtr.Zero,0,share,directory ? (parent==IntPtr.Zero ? 1u : 3u) : (fresh ? 2u : 1u),
            (directory ? 1u : 0x40u)|0x20u|0x00200000u,IntPtr.Zero,0);
        if(status>0) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE"); // do not read PENDING results
        IntPtr actual=Marshal.ReadIntPtr(r.HandleSlot);
        // Negative terminal failure with NO output handle is settled, never an open.
        // STATUS_PENDING / any positive informational / inconsistent success stays UNKNOWN.
        if(status<0 && (actual==IntPtr.Zero || actual==new IntPtr(-1))) {
            PublicSettled(owner,r); throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        }
        var io=Marshal.PtrToStructure<IoStatus>(r.Io);
        ulong result=io.Information.ToUInt64();
        if(status!=0 || io.Status!=IntPtr.Zero || actual==IntPtr.Zero || actual==new IntPtr(-1) ||
            (fresh ? result!=2 : (directory && parent!=IntPtr.Zero ? (result!=1 && result!=2) : result!=1)))
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        r.Handle=actual; r.Opened=true; PublicSettled(owner,r);
        CheckPublic(owner,actual,directory,directory ? 0 : (name.EndsWith(".binding.json",StringComparison.Ordinal) ? 64000 : 1900000));
        return actual;
    }
    public static IntPtr PublicDirectory(PublicStageOwner owner,string path) {
        // Fixed runtime ancestry, FILE_OPEN, READ/list + READ_ATTRIBUTES + SYNCHRONIZE,
        // share READ only (no write/delete), synchronous nonalert, open reparse itself.
        return PublicOpen(owner,IntPtr.Zero,"\\??\\"+path,true,false,1);
    }
    public static IntPtr PublicChild(PublicStageOwner owner,IntPtr parent,string name,bool directory) {
        if(!directory || (name!="state" && name!="guidance-public-exports"))
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        return PublicOpen(owner,parent,name,true,false,0); // SAME held relative namespace, FILE_OPEN_IF
    }
    static long PublicLeafCap(string name) {
        if(!System.Text.RegularExpressions.Regex.IsMatch(name,"\\A[0-9a-f]{32}\\.(body\\.txt|binding\\.json)\\z"))
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        return name.EndsWith(".body.txt",StringComparison.Ordinal) ? 1900000 : 64000;
    }
    public static long CheckPublic(PublicStageOwner owner,IntPtr h,bool directory,long cap) {
        PublicHeld(owner,h);
        Standard s; Tags t;
        if(GetFileType(h)!=1 || !GetStandard(h,1,out s,24) || !GetTags(h,9,out t,8) || s.DeletePending!=0 ||
            (s.Directory!=0)!=directory || (t.Attributes&0x400)!=0 || t.ReparseTag!=0 ||
            (!directory && (s.NumberOfLinks!=1 || s.EndOfFile<0 || s.EndOfFile>cap)))
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        return s.EndOfFile;
    }
    static long PublicScan(PublicStageOwner owner,IntPtr parent,int maxLeaves,bool admit) {
        PublicHeld(owner,parent);
        var r=PublicRequest(owner,parent,null,true);
        var seen=new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
        bool dot=false,dotdot=false;
        long bytes=0;
        // At most 32 leaves + TWO unique dot rows + terminal = 35 queries.
        // Single-entry 4096-byte buffer, no path reopen or arbitrary materialization.
        for(int row=0;row<35;row++) {
            PublicSubmit(owner,r); // reuse ONLY the fully terminal previous request/storage
            int status=NtQueryDirectoryFile(parent,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,r.Io,r.Buffer,4096,1,1,IntPtr.Zero,
                row==0 ? (byte)1 : (byte)0); // FileDirectoryInformation; ReturnSingleEntry; restart first ONLY
            if(status>0) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE"); // no PENDING result/buffer reads
            var io=Marshal.PtrToStructure<IoStatus>(r.Io);
            ulong got=io.Information.ToUInt64();
            if(status==unchecked((int)0x80000006)) { // STATUS_NO_MORE_FILES is terminal, not generic NT_SUCCESS
                if(got!=0) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
                PublicSettled(owner,r);
                if(!admit && seen.Count!=owner.Leaves.Count) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
                return bytes;
            }
            if(status<0) { PublicSettled(owner,r); throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE"); }
            if(status!=0 || io.Status!=IntPtr.Zero || got<64 || got>4096)
                throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE"); // graph remains UNKNOWN, no parsing
            PublicSettled(owner,r);
            int nameBytes=Marshal.ReadInt32(r.Buffer,60);
            if(Marshal.ReadInt32(r.Buffer,0)!=0 || nameBytes<2 || nameBytes>90 || (nameBytes&1)!=0 ||
                (ulong)(64+nameBytes)>got) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
            string name=Marshal.PtrToStringUni(IntPtr.Add(r.Buffer,64),nameBytes/2);
            if(name==".") { if(dot) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE"); dot=true; continue; }
            if(name=="..") { if(dotdot) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE"); dotdot=true; continue; }
            long cap=PublicLeafCap(name);
            if(seen.Count>=maxLeaves) throw new InvalidOperationException("MACHINE_EVIDENCE_LIMIT");
            if(!seen.Add(name)) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
            PublicLeaf leaf;
            if(admit) {
                leaf=new PublicLeaf {Cap=cap}; owner.Leaves.Add(name,leaf); // bounded map BEFORE open
                leaf.Handle=PublicOpen(owner,parent,name,false,false,0); // FILE_OPEN, exclusive READ; NEVER create/overwrite
                leaf.Length=CheckPublic(owner,leaf.Handle,false,cap);
            } else if(!owner.Leaves.TryGetValue(name,out leaf)) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
            long length=CheckPublic(owner,leaf.Handle,false,cap); // REAL retained leaf metadata, not directory row claims
            if(length!=leaf.Length) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
            bytes=checked(bytes+length);
            if(bytes>33554432) throw new InvalidOperationException("MACHINE_EVIDENCE_LIMIT");
        }
        throw new InvalidOperationException("MACHINE_EVIDENCE_LIMIT"); // no open/restart/retry beyond finite bound
    }
    public static void AdmitPublicInventory(PublicStageOwner owner,IntPtr parent,long body,long binding) {
        PublicReady(owner);
        if(owner.InventoryStarted || owner.Leaves.Count!=0 || body<1 || body>1900000 || binding<1 || binding>64000 ||
            body+binding>1964000) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        owner.InventoryStarted=true;
        owner.AdmittedBytes=PublicScan(owner,parent,30,true); // reserve TWO new leaves before admission
        if(owner.AdmittedBytes+body+binding>33554432) throw new InvalidOperationException("MACHINE_EVIDENCE_LIMIT");
    }
    public static IntPtr NewPublicLeaf(PublicStageOwner owner,IntPtr parent,string name) {
        PublicReady(owner); long cap=PublicLeafCap(name);
        if(!owner.InventoryStarted || owner.Leaves.Count>=32 || owner.Leaves.ContainsKey(name))
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        var leaf=new PublicLeaf {Cap=cap,Fresh=true}; owner.Leaves.Add(name,leaf);
        leaf.Handle=PublicOpen(owner,parent,name,false,true,0); // FILE_CREATE, collision refuses; READ+WRITE, share0
        if(CheckPublic(owner,leaf.Handle,false,cap)!=0) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        return leaf.Handle;
    }
    public static void RecheckPublicInventory(PublicStageOwner owner,IntPtr parent,bool complete,long body,long binding) {
        PublicReady(owner);
        int fresh=0;
        foreach(var pair in owner.Leaves) if(pair.Value.Fresh) {
            fresh++;
            long expected=complete ? (pair.Key.EndsWith(".body.txt",StringComparison.Ordinal) ? body : binding) : 0;
            if(CheckPublic(owner,pair.Value.Handle,false,pair.Value.Cap)!=expected)
                throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
            pair.Value.Length=expected;
        }
        if(fresh!=2) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        long actual=PublicScan(owner,parent,32,false);
        long expectedBytes=owner.AdmittedBytes+(complete ? body+binding : 0);
        if(actual!=expectedBytes || owner.AdmittedBytes+body+binding>33554432)
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        // Directory share0 serializes compliant exporters, NOT all hostile child additions.
        // Unknown/duplicate/missing additions at either bounded recheck fail closed.
    }
    static PublicManagedIo PublicStream(PublicStageOwner owner,IntPtr handle,FileAccess access,int buffer) {
        PublicHeld(owner,handle);
        var io=new PublicManagedIo(); owner.ManagedIo.Add(io); owner.Unknown=true;
        io.Alias=new SafeFileHandle(handle,false); // borrowed; actual handle remains in native request owner
        io.Stream=new FileStream(io.Alias,access,buffer,false); // documented synchronous managed I/O
        return io;
    }
    static void PublicDisposeIo(PublicStageOwner owner,PublicManagedIo io) {
        if(!io.Settled || io.DisposeAttempted) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        io.DisposeAttempted=true;
        if(io.Digest!=null) io.Digest.Dispose();
        io.Stream.Dispose(); io.Alias.Dispose(); io.Disposed=true;
        owner.ManagedIo.Remove(io); owner.Unknown=false; // ONLY observed completion AND disposal
    }
    public static void WritePublic(PublicStageOwner owner,IntPtr handle,byte[] bytes,long offset,long cap) {
        if(bytes.Length<1 || bytes.Length>8192 || CheckPublic(owner,handle,false,cap)!=offset || offset+bytes.Length>cap)
            throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        var io=PublicStream(owner,handle,FileAccess.Write,1); // buffer1 disables managed write buffering
        io.Bytes=bytes; io.Stream.Position=offset; io.Submitted=true;
        io.Stream.Write(io.Bytes,0,io.Bytes.Length); io.Stream.Flush(true); io.Settled=true;
        PublicDisposeIo(owner,io);
        // NO using/finally disposal after interrupted/failed write/flush: actual
        // stream/alias/byte buffer remains rooted, no hidden flush/retry on unwind.
    }
    public static string HashPublic(PublicStageOwner owner,IntPtr handle,long cap) {
        CheckPublic(owner,handle,false,cap);
        var io=PublicStream(owner,handle,FileAccess.Read,65536);
        io.Stream.Position=0;
        if(io.Stream.Length<0 || io.Stream.Length>cap) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
        io.Digest=SHA256.Create(); io.Submitted=true;
        string result=Convert.ToHexString(io.Digest.ComputeHash(io.Stream)).ToLowerInvariant(); io.Settled=true;
        PublicDisposeIo(owner,io); return result;
    }
    public static void ClosePublicStage(PublicStageOwner owner) {
        PublicReady(owner); owner.CloseAttempted=true; owner.Unknown=true;
        // Every actual native request is terminal BEFORE any close; no speculative
        // closing the slot/result of PENDING, and no retry after interrupted close.
        for(int i=owner.Requests.Count-1;i>=0;i--) {
            var r=owner.Requests[i];
            if(!r.Opened) continue;
            r.CloseAttempted=true;
            if(!CloseHandle(r.Handle)) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
            r.CloseConfirmed=true;
        }
        // Free ONLY after ALL actual handles have observed confirmed close.
        foreach(var r in owner.Requests) {
            if(r.Opened && !r.CloseConfirmed) throw new InvalidOperationException("MACHINE_EXPORT_UNAVAILABLE");
            foreach(var p in new IntPtr[] {r.Buffer,r.Attributes,r.Name,r.Text,r.HandleSlot,r.Io})
                if(p!=IntPtr.Zero) Marshal.FreeHGlobal(p);
        }
        owner.Closed=true; owner.Unknown=false;
    }
    public static IntPtr Open(string p, bool directory) {
        IntPtr h = CreateFileW(p, 0x80020000, directory ? 3u : 1u, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
        if(h == IntPtr.Zero || h == new IntPtr(-1)) throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE");
        return h; // PS owns/retains BEFORE any following metadata/ACL/hash query
    }
    public static long Check(IntPtr h, bool directory, bool ancestor) {
        Standard s; Tags t;
        if(!GetStandard(h,1,out s,24) || !GetTags(h,9,out t,8) || s.DeletePending!=0 ||
           (s.Directory!=0)!=directory || (t.Attributes&0x400)!=0 || t.ReparseTag!=0 ||
           (!directory && s.NumberOfLinks!=1)) throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE");
        IntPtr owner, group, dacl, sacl, sd;
        if(GetSecurityInfo(h,1,5,out owner,out group,out dacl,out sacl,out sd)!=0)
            throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE");
        try {
            uint length=GetSecurityDescriptorLength(sd);
            if(length==0 || length>65536) throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE");
            byte[] raw=new byte[length]; Marshal.Copy(sd,raw,0,raw.Length);
            RawSecurityDescriptor acl=new RawSecurityDescriptor(raw,0);
            string sid=acl.Owner.Value;
            Func<string,bool> trusted = v => v=="S-1-5-18" || v=="S-1-5-32-544" ||
                (ancestor && v=="S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464");
            if(!trusted(sid) || acl.DiscretionaryAcl==null || acl.DiscretionaryAcl.Count>256)
                throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE");
            foreach(GenericAce item in acl.DiscretionaryAcl) {
                CommonAce ace=item as CommonAce;
                if(ace==null || ace.IsCallback) throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE");
                if(ace.AceQualifier!=AceQualifier.AccessAllowed || (ace.AceFlags&AceFlags.InheritOnly)!=0) continue;
                uint dangerous=(uint)(ancestor ? 0xD0150 : 0xD0156) | 0x50000000u;
                if(!trusted(ace.SecurityIdentifier.Value) && (((uint)ace.AccessMask&dangerous)!=0))
                    throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE");
            }
        } finally { if(LocalFree(sd)!=IntPtr.Zero) throw new InvalidOperationException("GUIDANCE_ORIGIN_UNAVAILABLE"); }
        return s.EndOfFile;
    }
    public static string Hash(IntPtr handle, long cap) {
        using(var alias=new SafeFileHandle(handle,false))
        using(var stream=new FileStream(alias,FileAccess.Read,65536,false)) {
            if(stream.Length<0 || stream.Length>cap) throw new InvalidOperationException("GUIDANCE_ORIGIN_BOUND");
            using(var sha=SHA256.Create()) return Convert.ToHexString(sha.ComputeHash(stream)).ToLowerInvariant();
        }
    }
}
'@
}

function _GuidanceRetain([hashtable]$C) {
    if (-not $C.Retained) {
        $C.Retained = $true
        $script:RetainedGuidanceHosts.Add($C) # actual Process/tasks/pipes/guards, NOT cached authority
    }
    $C.Uncertain = $true
}

function _GuidanceReleaseOrigin([hashtable]$C) {
    if ($C.OriginClosed) { return }
    if ($C.OriginCloseAttempted) { throw 'GUIDANCE_ORIGIN_CLOSE_UNCONFIRMED' }
    # Retain exact actual parent key/handle graph BEFORE the first close/status
    # submission, including exceptions/interruptions. Other unresolved origins
    # veto all additional cleanup, not just a retry of the same handle.
    $blocked = $script:RetainedGuidanceOrigins.Count -gt 0
    $script:RetainedGuidanceOrigins.Add($C)
    $C.OriginCloseAttempted = $true
    $C.ParentOriginUncertain = $true
    try {
        if ($blocked) { throw 'GUIDANCE_ORIGIN_CLOSE_UNCONFIRMED' }
        foreach ($handle in $C.Handles) {
            if (-not [GuidanceParentOrigin]::CloseHandle($handle)) { throw 'GUIDANCE_ORIGIN_CLOSE_UNCONFIRMED' }
        }
        foreach ($key in $C.Keys) {
            $actual=$key.Handle # SAME retained SafeRegistryHandle, not a reconstructed key
            if ([GuidanceParentOrigin]::RegCloseKey($actual.DangerousGetHandle()) -ne 0) { throw 'GUIDANCE_ORIGIN_CLOSE_UNCONFIRMED' }
            $actual.SetHandleAsInvalid() # only confirmed RegCloseKey; never an implicit second close
            $key.Dispose()
        }
        $C.Handles.Clear()
        $C.Keys.Clear()
        $C.OriginClosed = $true # ONLY complete observed cleanup, never before submission
        $C.ParentOriginUncertain = $false
        $null = $script:RetainedGuidanceOrigins.Remove($C)
    } catch {
        _GuidanceRetain $C
        throw 'GUIDANCE_ORIGIN_CLOSE_UNCONFIRMED'
    }
}

function _GuidanceOrigin([hashtable]$C) {
    _GuidanceNativeDeclarations
    $hive = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,
                                                     [Microsoft.Win32.RegistryView]::Registry64)
    $C.Keys.Add($hive)
    $trusted = @('S-1-5-18','S-1-5-32-544')
    $owners = $trusted + @('S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
    foreach ($name in @('SOFTWARE','SOFTWARE\InvestorIntelligence','SOFTWARE\InvestorIntelligence\GuidanceProtected')) {
        $key = $hive.OpenSubKey($name, $false)
        if ($null -eq $key) { throw 'GUIDANCE_AUTHORITY_UNAVAILABLE' }
        $C.Keys.Add($key)
        $acl = [Microsoft.Win32.RegistryAclExtensions]::GetAccessControl($key)
        $allowed = if ($name -eq 'SOFTWARE\InvestorIntelligence\GuidanceProtected') { $trusted } else { $owners }
        if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $allowed) { throw 'GUIDANCE_AUTHORITY_UNAVAILABLE' }
        $rules = @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
        if ($rules.Count -gt 256) { throw 'GUIDANCE_AUTHORITY_UNAVAILABLE' }
        foreach ($rule in $rules) {
            if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
                ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -eq 0 -and
                $rule.IdentityReference.Value -notin $allowed -and
                (([int64]$rule.RegistryRights -band 0x500D0026) -ne 0)) { throw 'GUIDANCE_AUTHORITY_UNAVAILABLE' }
        }
    }
    foreach ($name in @('Approval','Installation','Enrollment')) {
        if ($key.GetValueKind($name) -ne [Microsoft.Win32.RegistryValueKind]::String) { throw 'GUIDANCE_AUTHORITY_UNAVAILABLE' }
    }
    $approval = _GuidanceJson ([string]$key.GetValue('Approval')) 2097152
    $installation = _GuidanceJson ([string]$key.GetValue('Installation')) 2097152
    $enrollment = _GuidanceJson ([string]$key.GetValue('Enrollment')) 2097152
    if (($approval.Keys | Sort-Object) -join ',' -cne 'files,release_id,runtime_sid,schema' -or
        $approval.schema -cne 'guidance-protected-approval-v1' -or $approval.release_id -cnotmatch '^[0-9a-f]{64}$' -or
        $approval.files.Count -gt 4096 -or $approval.files.Count -lt 24 -or
        $installation.schema -cne 'guidance-protected-install-v1' -or $installation.release_id -cne $approval.release_id -or
        $enrollment.schema -cne 'guidance-protected-enrollment-v1' -or $enrollment.release_id -cne $approval.release_id) {
        throw 'GUIDANCE_AUTHORITY_UNAVAILABLE'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        if ($identity.User.Value -cne $approval.runtime_sid -or
            ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'GUIDANCE_RUNTIME_PRINCIPAL_UNAVAILABLE'
        }
    } finally { $identity.Dispose() }
    $root = 'C:\Program Files\InvestorIntelligence\GuidanceProtected\releases\' + $approval.release_id
    $required = @('Python/python.exe','Python/python312.dll','scripts/revenue_guidance_bootstrap.py',
                  'scripts/revenue_guidance_provisioner.py','scripts/revenue_guidance_host.py',
                  'scripts/revenue_guidance_backend.psm1','scripts/bottleneck_top20_v3.py',
                  'scripts/publish_sealed_snapshot.py','scripts/order_forecast.py')
    foreach ($name in $required) { if (-not $approval.files.ContainsKey($name)) { throw 'GUIDANCE_CLOSURE_UNAVAILABLE' } }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $total = 0L
    foreach ($name in $approval.files.Keys) {
        if ($name.Length -gt 240 -or $name -cmatch '(^/|\\|:|(^|/)\.{1,2}(/|$)|\.pth$|\.pyc$)' -or
            $approval.files[$name] -cnotmatch '^[0-9a-f]{64}$' -or -not $seen.Add($name)) { throw 'GUIDANCE_CLOSURE_UNAVAILABLE' }
        $file = Join-Path $root $name
        $parent = [IO.DirectoryInfo]::new([IO.Path]::GetDirectoryName($file))
        $chain = [Collections.Generic.List[string]]::new()
        while ($null -ne $parent) { $chain.Add($parent.FullName); $parent=$parent.Parent }
        foreach ($directory in $chain) {
            if ($C.DirectorySet.Add($directory)) {
                if ($C.Handles.Count -ge 8192) { throw 'GUIDANCE_ORIGIN_BOUND' }
                $handle = [GuidanceParentOrigin]::Open($directory,$true)
                $C.Handles.Add($handle)
                $inside = $directory -ceq $root -or $directory.StartsWith($root + '\',[StringComparison]::OrdinalIgnoreCase)
                $null = [GuidanceParentOrigin]::Check($handle,$true,-not $inside)
            }
        }
        if ($C.Handles.Count -ge 8192) { throw 'GUIDANCE_ORIGIN_BOUND' }
        $handle = [GuidanceParentOrigin]::Open($file,$false)
        $C.Handles.Add($handle)
        $size = [GuidanceParentOrigin]::Check($handle,$false,$false)
        $total += $size
        if ($size -gt 268435456 -or $total -gt 536870912 -or
            [GuidanceParentOrigin]::Hash($handle,268435456) -cne $approval.files[$name]) { throw 'GUIDANCE_CLOSURE_UNAVAILABLE' }
    }
    # Complete actual inventory before interpreter launch. No writable import
    # directory, unapproved extra leaf, reparse descent or missed module closure.
    $inventory=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $directories=[Collections.Generic.Stack[string]]::new()
    $directories.Push($root)
    $count=0
    while ($directories.Count -gt 0) {
        $directory=$directories.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop) {
            $count++
            if ($count -gt 8192 -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'GUIDANCE_ORIGIN_BOUND' }
            if ($item.PSIsContainer) {
                if ($C.DirectorySet.Add($item.FullName)) {
                    if ($C.Handles.Count -ge 8192) { throw 'GUIDANCE_ORIGIN_BOUND' }
                    $handle=[GuidanceParentOrigin]::Open($item.FullName,$true)
                    $C.Handles.Add($handle)
                    $null=[GuidanceParentOrigin]::Check($handle,$true,$false)
                }
                $directories.Push($item.FullName)
            } else {
                $name=[IO.Path]::GetRelativePath($root,$item.FullName).Replace('\','/')
                if (-not $approval.files.ContainsKey($name) -or -not $inventory.Add($name)) { throw 'GUIDANCE_CLOSURE_UNAVAILABLE' }
            }
        }
    }
    if ($inventory.Count -ne $approval.files.Count) { throw 'GUIDANCE_CLOSURE_UNAVAILABLE' }
    return $root # private local executable selection, NEVER a transported proof
}

function _GuidanceRemaining([hashtable]$C) {
    [long]$remaining = $C.BudgetMs - $C.Clock.ElapsedMilliseconds
    if ($remaining -le 0) { return 0L }
    return [Math]::Min(600000L,$remaining)
}

function _GuidanceRead([hashtable]$C, [long]$Milliseconds) {
    # One existing async read task, retained on timeout. No cancel/dispose/kill.
    if ($null -ne $C.PendingRead) { throw 'GUIDANCE_READ_ALREADY_PENDING' }
    $C.PendingRead = [GuidanceParentOrigin]::ReadFrame($C.Process.StandardOutput)
    if ($Milliseconds -le 0 -or -not $C.PendingRead.Wait([int][Math]::Min($Milliseconds,600000))) {
        _GuidanceRetain $C
        throw 'GUIDANCE_HOST_ATTEMPTED_UNKNOWN'
    }
    $text = $C.PendingRead.GetAwaiter().GetResult()
    $C.PendingRead = $null
    if ($null -eq $text) { _GuidanceRetain $C; throw 'GUIDANCE_HOST_EOF_UNKNOWN' }
    return _GuidanceJson $text
}

function _GuidanceSend([hashtable]$C, [string]$Operation, [hashtable]$Arguments) {
    if ($C.Closed -or $C.Uncertain -or $C.Sequence -ge 64 -or $null -eq $C.Process) { throw 'GUIDANCE_SESSION_UNAVAILABLE' }
    $left = _GuidanceRemaining $C
    if ($Operation -ne 'Close' -and $left -le 0) { throw 'GUIDANCE_REFUSED_BEFORE_DISPATCH' }
    $next = $C.Sequence + 1
    $frame = @{protocol=$script:GuidanceProtocol; id=$next; op=$Operation; session=$C.SessionRef;
               remaining_ms=$left; deadline_utc=$C.DeadlineUtc; args=$Arguments} | ConvertTo-Json -Depth 16 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($frame) -gt 16384) { throw 'GUIDANCE_REFUSED_BEFORE_DISPATCH' }
    $C.Sequence = $next
    $C.InFlight = $true # before pipe submission; partial writes are NEVER resent
    try {
        $C.Process.StandardInput.WriteLine($frame)
        $C.Process.StandardInput.Flush()
        # Cleanup can start after budget only if no prior attempted unknown. It
        # is still not cancellation; no kill at expiry of this final observation.
        $reply = _GuidanceRead $C $(if ($Operation -eq 'Close') { 10000L } else { _GuidanceRemaining $C })
        if (($reply.Keys | Sort-Object) -join ',' -cne 'attempted,id,protocol,result,status' -or
            $reply.protocol -cne $script:GuidanceProtocol -or $reply.id -is [bool] -or
            ($reply.id -isnot [int] -and $reply.id -isnot [long]) -or $reply.id -ne $C.Sequence -or
            $reply.attempted -isnot [bool]) {
            _GuidanceRetain $C
            throw 'GUIDANCE_HOST_ATTEMPTED_UNKNOWN'
        }
        if ($Operation -ceq 'ExportPublicBundle' -and $reply.status -ceq 'PUBLIC_DATA_BEGIN' -and $reply.attempted) {
            $result=_GuidanceExportData $C $reply.result
            $C.InFlight=$false
            return $result
        }
        if ($reply.status -cne 'OK') {
            if ($reply.status -ceq 'REFUSED_BEFORE_DISPATCH' -and $reply.attempted -eq $false) {
                $C.InFlight = $false # correlated bounded refusal is not attempted UNKNOWN
                throw 'GUIDANCE_REFUSED_BEFORE_DISPATCH'
            }
            _GuidanceRetain $C
            if ($C.MachineEnabled -and $reply.result -is [hashtable] -and
                $reply.result.Reason -cin @('MACHINE_INPUTS_UNAVAILABLE','MACHINE_EVIDENCE_LIMIT','MACHINE_EXPORT_UNAVAILABLE','GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE')) {
                $C.MachineFailure=$reply.result.Reason
                throw $C.MachineFailure
            }
            throw 'GUIDANCE_HOST_OPERATION_UNAVAILABLE'
        }
        $C.InFlight = $false
        return $reply.result
    } catch {
        if ($C.InFlight) { _GuidanceRetain $C }
        $reason=$_.Exception.Message
        if ($C.MachineEnabled -and $reason -cin @('MACHINE_INPUTS_UNAVAILABLE','MACHINE_EVIDENCE_LIMIT','MACHINE_EXPORT_UNAVAILABLE','GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE')) {
            $C.MachineFailure=$reason
            throw $reason # actual typed machine failure preserved through transport/envelope/staging handler
        }
        throw 'GUIDANCE_HOST_OPERATION_UNAVAILABLE'
    }
}

function _GuidanceCloseStage([object]$Owner) {
    [GuidanceParentOrigin]::ClosePublicStage($Owner) # terminal-only graph, one close attempt; unknown never freed
    if (-not $Owner.Closed -or $Owner.Unknown) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
    $null=$script:RetainedGuidanceStages.Remove($Owner) # ONLY all confirmed close + allocation cleanup
}

function _GuidanceExportData([hashtable]$C, [hashtable]$Header) {
    if (-not $C.MachineEnabled -or $C.ExportStarted -or $script:RetainedGuidanceStages.Count -gt 0) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
    $C.ExportStarted=$true
    if (($Header.Keys | Sort-Object) -join ',' -cne 'BindingBytes,BindingSha256,BodyBytes,BodySha256,Cutoff,Revision' -or
        $Header.BodySha256 -cnotmatch '^[0-9a-f]{64}$' -or $Header.BindingSha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $Header.Revision -cne $C.LastRankingRevision -or $Header.Cutoff -cnotmatch '^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$' -or
        $Header.BodyBytes -is [bool] -or $Header.BindingBytes -is [bool] -or
        ($Header.BodyBytes -isnot [int] -and $Header.BodyBytes -isnot [long]) -or
        ($Header.BindingBytes -isnot [int] -and $Header.BindingBytes -isnot [long]) -or
        $Header.BodyBytes -lt 1 -or $Header.BodyBytes -gt 1900000 -or $Header.BindingBytes -lt 1 -or
        $Header.BindingBytes -gt 64000 -or ($Header.BodyBytes+$Header.BindingBytes) -gt 1964000) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
    $owner=[GuidanceParentOrigin+PublicStageOwner]::new()
    $script:RetainedGuidanceStages.Add($owner) # actual graph BEFORE ALL native staging submission
    $C.StageOwner=$owner
    # Fixed module/runtime PUBLIC location; no caller/packet-selected path. Held
    # no-reparse ancestors and relative NT child creation prevent traversal/reroute.
    $runtime=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $parents=[Collections.Generic.Stack[string]]::new()
    $dir=[IO.DirectoryInfo]::new($runtime)
    while ($null -ne $dir) {
        if ($parents.Count -ge 24 -or $dir.FullName.Length -gt 2044) { throw 'MACHINE_EVIDENCE_LIMIT' }
        $parents.Push($dir.FullName); $dir=$dir.Parent
    }
    while ($parents.Count -gt 0) { $rootHandle=[GuidanceParentOrigin]::PublicDirectory($owner,$parents.Pop()) }
    $stateHandle=[GuidanceParentOrigin]::PublicChild($owner,$rootHandle,'state',$true)
    $stageHandle=[GuidanceParentOrigin]::PublicChild($owner,$stateHandle,'guidance-public-exports',$true)
    [GuidanceParentOrigin]::AdmitPublicInventory($owner,$stageHandle,$Header.BodyBytes,$Header.BindingBytes)
    $leafNonce=[Guid]::NewGuid().ToString('N')
    $bodyHandle=[GuidanceParentOrigin]::NewPublicLeaf($owner,$stageHandle,($leafNonce+'.body.txt'))
    $bindingHandle=[GuidanceParentOrigin]::NewPublicLeaf($owner,$stageHandle,($leafNonce+'.binding.json'))
    [GuidanceParentOrigin]::RecheckPublicInventory($owner,$stageHandle,$false,$Header.BodyBytes,$Header.BindingBytes)
    $chunks=0
    foreach ($name in @('body','binding')) {
        $length=if ($name -ceq 'body') {$Header.BodyBytes} else {$Header.BindingBytes}
        $handle=if ($name -ceq 'body') {$bodyHandle} else {$bindingHandle}
        [long]$offset=0
        while ($offset -lt $length) {
            if ($chunks -ge 256 -or (_GuidanceRemaining $C) -le 0) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
            $frame=_GuidanceRead $C (_GuidanceRemaining $C)
            if (($frame.Keys | Sort-Object) -join ',' -cne 'bytes,chunk,data,id,object,offset,protocol,status' -or
                $frame.protocol -cne $script:GuidanceProtocol -or $frame.id -is [bool] -or
                ($frame.id -isnot [int] -and $frame.id -isnot [long]) -or $frame.id -ne $C.Sequence -or $frame.status -cne 'PUBLIC_DATA' -or
                $frame.object -cne $name -or $frame.offset -ne $offset -or $frame.chunk -ne $chunks -or
                $frame.offset -is [bool] -or $frame.chunk -is [bool] -or $frame.bytes -is [bool] -or
                ($frame.offset -isnot [int] -and $frame.offset -isnot [long]) -or
                ($frame.chunk -isnot [int] -and $frame.chunk -isnot [long]) -or
                ($frame.bytes -isnot [int] -and $frame.bytes -isnot [long]) -or
                $frame.bytes -lt 1 -or $frame.bytes -gt 8192 -or $frame.bytes -gt $length-$offset -or
                $frame.data -isnot [string] -or $frame.data.Length -gt 10924 -or $frame.data -cnotmatch '^[A-Za-z0-9+/]*={0,2}$') {
                throw 'MACHINE_EXPORT_UNAVAILABLE'
            }
            $raw=[Convert]::FromBase64String($frame.data)
            if ($raw.Length -ne $frame.bytes -or [Convert]::ToBase64String($raw) -cne $frame.data) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
            [GuidanceParentOrigin]::WritePublic($owner,$handle,$raw,$offset,$length)
            $offset += $raw.Length; $chunks++
        }
    }
    $terminal=_GuidanceRead $C (_GuidanceRemaining $C)
    if (($terminal.Keys | Sort-Object) -join ',' -cne 'attempted,id,protocol,result,status' -or
        $terminal.protocol -cne $script:GuidanceProtocol -or $terminal.id -is [bool] -or
        ($terminal.id -isnot [int] -and $terminal.id -isnot [long]) -or $terminal.id -ne $C.Sequence -or $terminal.status -cne 'OK' -or
        $terminal.attempted -isnot [bool] -or -not $terminal.attempted -or $terminal.result.Exported -isnot [bool] -or
        -not $terminal.result.Exported -or $terminal.result.Chunks -is [bool] -or
        ($terminal.result.Chunks -isnot [int] -and $terminal.result.Chunks -isnot [long]) -or
        $terminal.result.Chunks -ne $chunks -or ($terminal.result.Keys | Sort-Object) -join ',' -cne
        'BindingBytes,BindingSha256,BodyBytes,BodySha256,Chunks,Cutoff,Exported,Revision') { throw 'MACHINE_EXPORT_UNAVAILABLE' }
    foreach ($key in $Header.Keys) { if ($terminal.result[$key] -cne $Header[$key]) { throw 'MACHINE_EXPORT_UNAVAILABLE' } }
    [GuidanceParentOrigin]::RecheckPublicInventory($owner,$stageHandle,$true,$Header.BodyBytes,$Header.BindingBytes)
    if ([GuidanceParentOrigin]::CheckPublic($owner,$bodyHandle,$false,1900000) -ne $Header.BodyBytes -or
        [GuidanceParentOrigin]::CheckPublic($owner,$bindingHandle,$false,64000) -ne $Header.BindingBytes -or
        [GuidanceParentOrigin]::HashPublic($owner,$bodyHandle,1900000) -cne $Header.BodySha256 -or
        [GuidanceParentOrigin]::HashPublic($owner,$bindingHandle,64000) -cne $Header.BindingSha256) { throw 'MACHINE_EXPORT_UNAVAILABLE' }
    # Independent private-channel digests retained separately from writable data.
    $C.PublicBundle=[pscustomobject]@{RunId=$C.PublicRunId
        Token=$leafNonce
        BodySha256=$Header.BodySha256;BindingSha256=$Header.BindingSha256}
    _GuidanceCloseStage $owner
    return @{Exported=$true}
}

function _GuidanceVersion([hashtable]$C, [hashtable]$Reply) {
    if ($Reply.VersionRef -cnotmatch '^[0-9a-f]{48}$') { throw 'GUIDANCE_VERSION_UNAVAILABLE' }
    # PS-side opaque object identity also retained. Only this private original
    # object resolves to its session ref; callers cannot recreate it from fields.
    $C.Version = [pscustomobject]@{ Ref=$Reply.VersionRef; Session=$C.SessionRef }
    return [pscustomobject]@{ State=$Reply.State; Version=$C.Version }
}

function _GuidanceLeaseOperation([hashtable]$C, [string]$Op, [object]$Expected=$null, [object]$Value=$null) {
    if ($C.Closed) { throw 'GUIDANCE_SESSION_CLOSED' }
    switch ($Op) {
        'ReadJournal' { return _GuidanceVersion $C (_GuidanceSend $C $Op @{}) }
        'ReadInputRevision' { return (_GuidanceSend $C $Op @{}).Revision }
        'CommitJournal' {
            if (-not [object]::ReferenceEquals($Expected,$C.Version)) { throw 'GUIDANCE_VERSION_UNAVAILABLE' }
            $reply = _GuidanceSend $C $Op @{VersionRef=$C.Version.Ref;NewState=$Value}
            $journal = _GuidanceVersion $C $reply
            return [pscustomobject]@{ Committed=$reply.Committed;State=$journal.State;Version=$journal.Version }
        }
        'CheckRelease' { return _GuidanceSend $C $Op @{} }
        'Update' { return _GuidanceSend $C $Op @{} }
        'ReadRebuildCompletion' { return _GuidanceSend $C $Op @{Revision=$Value} }
        'RankAndComplete' {
            $result = _GuidanceSend $C $Op @{Mode=$Expected;Revision=$Value}
            if ($result.Completed -isnot [bool] -or $result.Revision -cnotmatch '^gir1:[0-9a-f]{64}$') {
                _GuidanceRetain $C; throw 'GUIDANCE_RANKING_RESULT_UNAVAILABLE'
            }
            $progress = $result.ContainsKey('AcquisitionProgress') -and $result.AcquisitionProgress -is [bool] -and $result.AcquisitionProgress
            if ($progress -and ($result.Completed -or $result.Reason -cne 'ACQUISITION_PENDING' -or
                $result.Progress -isnot [hashtable] -or ($result.Progress.Keys | Sort-Object) -join ',' -cne 'Cursor,Slots,Stage' -or
                $result.Progress.Stage -cnotin @('base','auxiliary','cision-pages','dynamic') -or
                ($result.Progress.Cursor -isnot [int] -and $result.Progress.Cursor -isnot [long]) -or
                ($result.Progress.Slots -isnot [int] -and $result.Progress.Slots -isnot [long]) -or
                $result.Progress.Slots -lt 1 -or $result.Progress.Slots -gt 1024 -or
                $result.Progress.Cursor -lt 0 -or $result.Progress.Cursor -ge $result.Progress.Slots)) {
                _GuidanceRetain $C; throw 'GUIDANCE_ACQUISITION_RESULT_UNAVAILABLE'
            }
            if ($C.MachineEnabled -and $result.Completed) {
                $C.LastRankingRevision=$result.Revision
                $null=_GuidanceSend $C 'ExportPublicBundle' @{} # live witness/public readbacks BEFORE orchestration ACK/Close
            }
            return [pscustomobject]@{ExitCode=$(if ($result.Completed) {0} else {1});Completed=$result.Completed;
                Revision=$result.Revision;AcquisitionProgress=$progress;
                Lines=$(if ($progress) {@('GUIDANCE_ACQUISITION_PENDING')} else {@()})}
        }
        'Close' {
            # Mark BEFORE attempt. Unknown client/native state is NOT closeable;
            # keep actual child/tasks/pipes instead of killing or launching another.
            if ($C.CloseAttempted) { throw 'GUIDANCE_CLOSE_ALREADY_ATTEMPTED' }
            $C.CloseAttempted=$true
            if ($C.Uncertain) { _GuidanceRetain $C; throw 'GUIDANCE_CLOSE_UNAVAILABLE_RETAINED' }
            $result = _GuidanceSend $C $Op @{}
            if ($result.Closed -isnot [bool] -or $result.Closed -ne $true -or $result.Custody -cne 'SETTLED') {
                _GuidanceRetain $C; throw 'GUIDANCE_CLOSE_UNAVAILABLE_RETAINED'
            }
            _GuidanceRetain $C # retain BEFORE all exit/task/pipe cleanup, not only false Wait returns
            $C.Closed=$true
            $C.Version=$null
            $cleanupClock=[Diagnostics.Stopwatch]::StartNew()
            if (-not $C.Process.WaitForExit(10000)) { throw 'GUIDANCE_EXIT_UNCONFIRMED_RETAINED' }
            if ($C.Process.ExitCode -ne 0) { throw 'GUIDANCE_CLOSE_FAILED' }
            $left=[Math]::Max(0L,10000L - $cleanupClock.ElapsedMilliseconds)
            if ($left -le 0 -or -not $C.StderrTask.Wait([int]$left)) { throw 'GUIDANCE_DIAGNOSTIC_END_UNCONFIRMED' }
            $null=$C.StderrTask.GetAwaiter().GetResult()
            $C.Process.StandardInput.Dispose()
            $C.Process.StandardOutput.Dispose()
            $C.Process.StandardError.Dispose()
            $C.Process.Dispose() # ONLY explicit settled CLOSE ACK + actual exit + drained tasks
            $C.MachineReady=$C.MachineEnabled -and $result.ContainsKey('MachineAcknowledged') -and
                $result.MachineAcknowledged -is [bool] -and $result.MachineAcknowledged -and $null -ne $C.PublicBundle
            $C.Uncertain=$false
            $C.Retained=$false
            $null=$script:RetainedGuidanceHosts.Remove($C)
            return
        }
        default { throw 'GUIDANCE_OPERATION_REFUSED' }
    }
}

function _GuidanceOpen([hashtable]$C) {
    if (-not $C.Enabled -or $C.Used -or $script:RetainedGuidanceHosts.Count -gt 0 -or
        $script:RetainedGuidanceOrigins.Count -gt 0 -or $script:RetainedGuidanceStages.Count -gt 0) {
        return [pscustomobject]@{Available=$false;Reason='GUIDANCE_PROVIDER_UNAVAILABLE'}
    }
    $C.Used=$true
    if ($PSVersionTable.PSVersion -lt [version]'7.4' -or (_GuidanceRemaining $C) -le 0) {
        return [pscustomobject]@{Available=$false;Reason='GUIDANCE_PREREQUISITE_UNAVAILABLE'}
    }
    $handed=$false
    try {
        $root = _GuidanceOrigin $C
        $left = _GuidanceRemaining $C
        if ($left -le 0) { throw 'GUIDANCE_REFUSED_BEFORE_DISPATCH' }
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = Join-Path $root 'Python\python.exe'
        $start.WorkingDirectory = $root
        $start.UseShellExecute=$false
        $start.CreateNoWindow=$true
        $start.RedirectStandardInput=$start.RedirectStandardOutput=$start.RedirectStandardError=$true
        $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false,$true)
        $start.StandardInputEncoding=[Text.UTF8Encoding]::new($false,$true)
        $start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false,$true)
        foreach ($arg in @('-I','-S','-B',(Join-Path $root 'scripts\revenue_guidance_bootstrap.py'),'host','--remaining-ms',[string]$left)) {
            $start.ArgumentList.Add($arg)
        }
        $C.Process=[Diagnostics.Process]::new()
        $C.Process.StartInfo=$start
        $C.StartAttempted=$true
        if (-not $C.Process.Start()) { _GuidanceRetain $C; throw 'GUIDANCE_START_UNKNOWN' }
        # Drain into bounded safe tokens only; NEVER raw exception/contact data.
        $C.StderrTask=[GuidanceParentOrigin]::DrainSafeDiagnostics($C.Process.StandardError)
        $ready=_GuidanceRead $C (_GuidanceRemaining $C)
        if ($ready.protocol -cne $script:GuidanceProtocol -or $ready.id -ne 0 -or $ready.status -cne 'HOST_PROTOCOL_READY') {
            _GuidanceRetain $C; throw 'GUIDANCE_READY_UNAVAILABLE'
        }
        _GuidanceReleaseOrigin $C # child independently re-admitted full protected origin
        $openArgs=if ($C.MachineEnabled) {@{GuidanceMachineEnabled=$true}} else {@{}}
        $opened=_GuidanceSend $C 'Open' $openArgs
        if ($opened.Available -isnot [bool] -or $opened.Available -ne $true -or $opened.SessionRef -cnotmatch '^[0-9a-f]{48}$') {
            _GuidanceRetain $C; throw 'GUIDANCE_SESSION_UNAVAILABLE'
        }
        $C.SessionRef=$opened.SessionRef
        $dispatch=${function:_GuidanceLeaseOperation}
        $lease=[pscustomobject]@{
            ReadJournal={ & $dispatch $C 'ReadJournal' }.GetNewClosure()
            ReadInputRevision={ & $dispatch $C 'ReadInputRevision' }.GetNewClosure()
            CommitJournal={param($Version,$State) & $dispatch $C 'CommitJournal' $Version $State}.GetNewClosure()
            CheckRelease={ & $dispatch $C 'CheckRelease' }.GetNewClosure()
            Update={ & $dispatch $C 'Update' }.GetNewClosure()
            ReadRebuildCompletion={param($Revision) & $dispatch $C 'ReadRebuildCompletion' $null $Revision}.GetNewClosure()
            Close={ & $dispatch $C 'Close' }.GetNewClosure()
        }
        $handed=$true
        return [pscustomobject]@{Available=$true;Lease=$lease}
    } catch {
        if ($C.StartAttempted) { _GuidanceRetain $C }
        return [pscustomobject]@{Available=$false;Reason='GUIDANCE_PROVIDER_UNAVAILABLE'}
    } finally {
        if (-not $handed -and -not $C.OriginClosed -and -not $C.OriginCloseAttempted) {
            _GuidanceReleaseOrigin $C # parent owns origin even when CHILD outcome is unknown
        }
        # NO process Kill/Stop/Dispose/replacement on timeout/EOF/unknown/finally.
    }
}

function _GuidanceObservationDeclarations {
    if ('GuidanceProcessObservation' -as [type]) { return }
    # Separate .NET Framework-compatible declaration: enabled production caller
    # may itself be PS5.1 while its daily child must be protected-adapter PS7.4+.
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
public static class GuidanceProcessObservation {
    public sealed class MachineCapture {
        public readonly string ExpectedRun; public bool Seen,Invalid;
        public string Token,BodySha256,BindingSha256,ErrorReason;
        public MachineCapture(string run) { if(!Regex.IsMatch(run,"^[0-9a-f]{32}$")) throw new InvalidOperationException("MACHINE_INPUTS_UNAVAILABLE"); ExpectedRun=run; }
    }
    public static async Task DrainMachine(StreamReader reader,MachineCapture capture) {
        char[] buffer=new char[512]; StringBuilder line=new StringBuilder(256); bool dropping=false;
        while(true) {
            int got=await reader.ReadAsync(buffer,0,buffer.Length).ConfigureAwait(false);
            if(got==0) { if(line.Length>0 && line.ToString().StartsWith("GUIDANCE_MACHINE_RESULT_V1|")) capture.Invalid=true; return; }
            for(int i=0;i<got;i++) {
                char ch=buffer[i];
                if(ch=='\n') {
                    if(!dropping) {
                        string text=line.ToString().TrimEnd('\r');
                        if(text.StartsWith("GUIDANCE_MACHINE_ERROR_V1|")) {
                            var error=Regex.Match(text,"^GUIDANCE_MACHINE_ERROR_V1\\|([0-9a-f]{32})\\|(MACHINE_INPUTS_UNAVAILABLE|MACHINE_EVIDENCE_LIMIT|MACHINE_EXPORT_UNAVAILABLE|GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE)$");
                            if(!error.Success || error.Groups[1].Value!=capture.ExpectedRun || capture.Seen || capture.ErrorReason!=null) capture.Invalid=true;
                            else capture.ErrorReason=error.Groups[2].Value;
                        }
                        if(text.StartsWith("GUIDANCE_MACHINE_RESULT_V1|")) {
                            if(capture.Seen || capture.ErrorReason!=null) capture.Invalid=true;
                            capture.Seen=true;
                            var m=Regex.Match(text,"^GUIDANCE_MACHINE_RESULT_V1\\|([0-9a-f]{32})\\|([0-9a-f]{32})\\|([0-9a-f]{64})\\|([0-9a-f]{64})$");
                            if(!m.Success || m.Groups[1].Value!=capture.ExpectedRun) capture.Invalid=true;
                            else {
                                var leafNonce=m.Groups[2].Value;
                                capture.Token=leafNonce;
                                capture.BodySha256=m.Groups[3].Value; capture.BindingSha256=m.Groups[4].Value;
                            }
                        }
                    }
                    line.Clear(); dropping=false;
                } else if(!dropping) {
                    if(line.Length>=512) { if(line.ToString().StartsWith("GUIDANCE_MACHINE_RESULT_V1|")) capture.Invalid=true; line.Clear(); dropping=true; }
                    else line.Append(ch);
                }
            }
        }
    }
    public static async Task Drain(StreamReader reader) {
        char[] buffer = new char[512];
        while(await reader.ReadAsync(buffer,0,buffer.Length).ConfigureAwait(false)>0) {
            // Fixed memory, discard all raw child diagnostics/contact text.
        }
    }
    public static Task Exit(Process process) {
        return Task.Run(() => process.WaitForExit()); // retained; no cancellation/kill
    }
}
'@
}

function _GuidanceQuoteArgument([string]$Argument) {
    # CommandLineToArgvW/CRT quoting, including embedded quotes/trailing slashes.
    # Fixed caller operands only; no cmd.exe, shell evaluation or command text.
    $escaped = [regex]::Replace($Argument, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Invoke-GuidanceObservedProcess {
    [CmdletBinding()]
    param([string]$Label, [string]$Executable, [string[]]$Arguments, [string]$WorkingDirectory,
          [ValidateRange(0,600000)][long]$RemainingMilliseconds, [AllowNull()][AllowEmptyString()][string]$MachineRunId=$null)
    $machineRequested=$PSBoundParameters.ContainsKey('MachineRunId') # presence, NEVER typed-string null conversion
    if ($machineRequested -and $MachineRunId -cnotmatch '\A[0-9a-f]{32}\z') { throw 'MACHINE_INPUTS_UNAVAILABLE' }
    if ($RemainingMilliseconds -le 0) {
        return [pscustomobject]@{ExitCode=125;Attempted=$false;Completed=$false;Status='NOT_ATTEMPTED_BUDGET';Lines=@()}
    }
    if ($script:ObservedGuidanceProcesses.Count -ge 16 -or
        @($script:ObservedGuidanceProcesses | Where-Object { $_.Label -ceq $Label }).Count -gt 0) {
        return [pscustomobject]@{ExitCode=125;Attempted=$false;Completed=$false;Status='NOT_ATTEMPTED_OWNER_RETAINED';Lines=@()}
    }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $context = @{Label=$Label;Process=$null;Stdout=$null;Stderr=$null;ExitTask=$null;Attempted=$false;CloseAttempted=$false;MachineCapture=$null}
    try {
        _GuidanceObservationDeclarations
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName=$Executable
        $start.Arguments=(@($Arguments | ForEach-Object { _GuidanceQuoteArgument $_ }) -join ' ')
        $start.WorkingDirectory=$WorkingDirectory
        $start.UseShellExecute=$false
        $start.CreateNoWindow=$true
        $start.RedirectStandardOutput=$start.RedirectStandardError=$true
        $context.Process=[Diagnostics.Process]::new()
        $context.Process.StartInfo=$start
        if ($clock.ElapsedMilliseconds -ge $RemainingMilliseconds) {
            $context.Process.Dispose() # no process submission, no native authority
            return [pscustomobject]@{ExitCode=125;Attempted=$false;Completed=$false;Status='NOT_ATTEMPTED_BUDGET';Lines=@()}
        }
        # Exact actual Process and later pipes/tasks rooted before Start. Failed
        # or interrupted submission is unknown, never retried/replaced/disposed.
        $script:ObservedGuidanceProcesses.Add($context)
        $context.Attempted=$true
        if (-not $context.Process.Start()) { throw 'GUIDANCE_CHILD_START_UNKNOWN' }
        if ($machineRequested) {
            $context.MachineCapture=[GuidanceProcessObservation+MachineCapture]::new($MachineRunId)
            $context.Stdout=[GuidanceProcessObservation]::DrainMachine($context.Process.StandardOutput,$context.MachineCapture)
        } else { $context.Stdout=[GuidanceProcessObservation]::Drain($context.Process.StandardOutput) }
        $context.Stderr=[GuidanceProcessObservation]::Drain($context.Process.StandardError)
        $context.ExitTask=[GuidanceProcessObservation]::Exit($context.Process)
        foreach ($task in @($context.ExitTask,$context.Stdout,$context.Stderr)) {
            $left=[Math]::Max(0L,$RemainingMilliseconds - $clock.ElapsedMilliseconds)
            if ($left -le 0 -or -not $task.Wait([int]$left)) { throw 'GUIDANCE_CHILD_ATTEMPTED_UNKNOWN' }
            $null=$task.GetAwaiter().GetResult()
        }
        $code=$context.Process.ExitCode
        $context.CloseAttempted=$true # graph retained before the one actual cleanup attempt
        $context.Process.StandardOutput.Dispose()
        $context.Process.StandardError.Dispose()
        $context.Process.Dispose()
        $null=$script:ObservedGuidanceProcesses.Remove($context)
        $machineBundle=$null
        if ($machineRequested -and $code -eq 0 -and $context.MachineCapture.Seen -and -not $context.MachineCapture.Invalid) {
            $mNonce=$context.MachineCapture.Token
            $machineBundle=[pscustomobject]@{RunId=$MachineRunId
                Token=$mNonce
                BodySha256=$context.MachineCapture.BodySha256;BindingSha256=$context.MachineCapture.BindingSha256}
        }
        return [pscustomobject]@{ExitCode=$code;Attempted=$true;Completed=$true;Status='EXIT_OBSERVED';Lines=@();
            MachineBundle=$machineBundle;MachineReason=$(if ($machineRequested -and $null -eq $machineBundle) {if (-not $context.MachineCapture.Invalid -and $null -ne $context.MachineCapture.ErrorReason) {$context.MachineCapture.ErrorReason} else {'MACHINE_EXPORT_UNAVAILABLE'}} else {$null})}
    } catch {
        if ($context.Attempted) {
            return [pscustomobject]@{ExitCode=124;Attempted=$true;Completed=$false;Status='ATTEMPTED_UNKNOWN_RETAINED';Lines=@()}
        }
        return [pscustomobject]@{ExitCode=125;Attempted=$false;Completed=$false;Status='NOT_ATTEMPTED_PREREQUISITE';Lines=@()}
    }
}

function Wait-GuidanceCustody {
    # Actual executable finally calls this AFTER bounded continuation/reporting.
    # Parent-owned unconfirmed OS origins differ from CHILD timeout: the latter
    # leaves authority inside the child, but its real parent pipe/task graph is
    # still rooted here. No status polling, close retry, kill, ACK or replacement.
    if ($script:RetainedGuidanceOrigins.Count -eq 0 -and $script:RetainedGuidanceHosts.Count -eq 0 -and
        $script:ObservedGuidanceProcesses.Count -eq 0 -and $script:RetainedGuidanceStages.Count -eq 0) { return }
    $emitted=$false
    while ($true) {
        try {
            if (-not $emitted) {
                $emitted=$true
                $guidanceOutcome=if ($script:RetainedGuidanceOrigins.Count -gt 0) {'GUIDANCE_PARENT_ORIGIN_UNRESOLVED'} else {'GUIDANCE_CHILD_GRAPH_RETAINED'}
                Write-Host $guidanceOutcome
            }
            $null=$script:GuidanceLifetimeEvent.WaitOne() # unsignalled lifetime only
        } catch { continue } # interruption is not permission to unload exact owner graphs
    }
}

function New-GuidanceBackend {
    [CmdletBinding()]
    param([bool]$Enabled=$false, [ValidateRange(1,600000)][long]$RemainingMilliseconds=600000,
          [bool]$MachineEnabled=$false, [string]$PublicRunId=$null)
    if ($MachineEnabled -and (-not $Enabled -or $PublicRunId -cnotmatch '^[0-9a-f]{32}$')) { throw 'MACHINE_INPUTS_UNAVAILABLE' }
    $context=@{Enabled=$Enabled;MachineEnabled=$MachineEnabled;PublicRunId=$PublicRunId;PublicBundle=$null;
        MachineReady=$false;MachineFailure=$null;ExportStarted=$false;LastRankingRevision=$null;StageOwner=$null;Used=$false;Closed=$false;CloseAttempted=$false;Uncertain=$false;Retained=$false;
        InFlight=$false;Sequence=0;SessionRef=$null;Version=$null;Process=$null;PendingRead=$null;StderrTask=$null;
        StartAttempted=$false;OriginClosed=$false;OriginCloseAttempted=$false;ParentOriginUncertain=$false;Handles=[Collections.Generic.List[IntPtr]]::new();
        Keys=[Collections.Generic.List[object]]::new();DirectorySet=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase);
        BudgetMs=$RemainingMilliseconds;Clock=$null;DeadlineUtc=$null}
    if ($Enabled) {
        $context.Clock=[Diagnostics.Stopwatch]::StartNew()
        $context.DeadlineUtc=[DateTime]::UtcNow.AddMilliseconds($RemainingMilliseconds).ToString('o')
    }
    $open=${function:_GuidanceOpen}
    $dispatch=${function:_GuidanceLeaseOperation}
    [pscustomobject]@{
        BackendFactory=[pscustomobject]@{OpenSession={ & $open $context }.GetNewClosure()}
        GetMachineFailure={ return $context.MachineFailure }.GetNewClosure()
        GetPublicBundle={
            if (-not $context.MachineEnabled -or -not $context.MachineReady -or -not $context.Closed -or $context.Uncertain) {
                throw 'MACHINE_EXPORT_UNAVAILABLE'
            }
            return $context.PublicBundle # public data only AFTER genuine normal ACK + settled Close/exit
        }.GetNewClosure()
        RunGuidanceRanking={param([string]$Mode,[object]$Revision)
            if (-not $context.Enabled -or $null -eq $context.SessionRef) { throw 'GUIDANCE_RANKING_UNAVAILABLE' }
            & $dispatch $context 'RankAndComplete' $Mode $Revision
        }.GetNewClosure()
    }
}
Export-ModuleMember -Function 'New-GuidanceBackend','Invoke-GuidanceObservedProcess','Wait-GuidanceCustody'
