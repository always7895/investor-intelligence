# Publication only: no Worker deployment, schedule registration or LINE send.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'v213_windows_security.ps1')
. (Join-Path $PSScriptRoot 'v213_operation_lock.ps1')

function Get-V213SealedPublicationPreference {
    param([string]$Path=(Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/v213-refresh-tasks.json'))
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $false}
    try{$state=Get-Content -LiteralPath $Path -Raw -Encoding utf8|ConvertFrom-Json}catch{throw 'V213_REFRESH_PREFERENCE_INVALID'}
    if($state-isnot[pscustomobject]){throw 'V213_REFRESH_PREFERENCE_INVALID'}
    $property=$state.PSObject.Properties['sealed_publication_enabled']
    if($null-eq$property){return $false}
    if($property.Value-isnot[bool]){throw 'V213_REFRESH_PREFERENCE_INVALID'}
    return $property.Value
}

function Save-V213RefreshJournal($Record,[string]$Path) {
    $Record|ConvertTo-Json -Depth 8|Set-Content -LiteralPath ($Path+'.tmp') -Encoding utf8
    Move-Item -LiteralPath ($Path+'.tmp') -Destination $Path -Force
}
function Read-V213RefreshJournal([string]$Path) {
    # Bind bytes, digest and parsed fields to one bounded read. This is not a
    # durable file-identity/parent lock or a metadata replacement primitive.
    $stream=$null;$hasher=$null
    try {
        $attributes=[IO.File]::GetAttributes($Path)
        if(($attributes-band([IO.FileAttributes]::Directory-bor[IO.FileAttributes]::ReparsePoint))-ne0){throw 'INVALID'}
        $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        if($stream.Length-lt1-or$stream.Length-gt262144){throw 'INVALID'}
        $bytes=New-Object byte[] ([int]$stream.Length)
        $offset=0
        while($offset-lt$bytes.Length){
            $read=$stream.Read($bytes,$offset,$bytes.Length-$offset)
            if($read-le0){throw 'INVALID'}
            $offset+=$read
        }
        if($stream.ReadByte()-ne-1){throw 'INVALID'}
        $stream.Dispose();$stream=$null
        $hasher=[Security.Cryptography.SHA256]::Create()
        $digest=[BitConverter]::ToString($hasher.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()
        $text=(New-Object Text.UTF8Encoding($false,$true)).GetString($bytes)
        if($text.Length-gt0-and$text[0]-eq[char]0xfeff){$text=$text.Substring(1)}
        # ConvertFrom-Json can discard duplicate keys. Check decoded names at
        # every object level before using its result (including escaped aliases).
        $pattern='\G(?:[ \t\r\n]+|"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|[{}\[\]:,]|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)'
        $lexer=[regex]::new($pattern,[Text.RegularExpressions.RegexOptions]::CultureInvariant,[TimeSpan]::FromMilliseconds(250))
        $tokens=[Collections.Generic.List[string]]::new();$position=0
        while($position-lt$text.Length){
            $match=$lexer.Match($text,$position)
            if(-not$match.Success-or$match.Index-ne$position){throw 'INVALID'}
            $position+=$match.Length
            if(-not[string]::IsNullOrWhiteSpace($match.Value)){$tokens.Add($match.Value)}
            if($tokens.Count-gt32768){throw 'INVALID'}
        }
        # PS7 can enumerate a one-element array into a PSCustomObject. Admit
        # the original root token, not just the post-conversion PowerShell type.
        if($tokens.Count-lt2-or$tokens[0]-cne'{'-or$tokens[$tokens.Count-1]-cne'}'){throw 'INVALID'}
        $objects=[Collections.Stack]::new()
        for($i=0;$i-lt$tokens.Count;$i++){
            $token=$tokens[$i]
            if($token-ceq'{'){$objects.Push(@{Kind='object';Names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)})}
            elseif($token-ceq'['){$objects.Push(@{Kind='array'})}
            elseif($token-cin@('}',']')){
                if($objects.Count-eq0){throw 'INVALID'}
                [void]$objects.Pop()
            } elseif($i+1-lt$tokens.Count-and$tokens[$i+1]-ceq':'){
                if(-not$token.StartsWith('"')-or$objects.Count-eq0-or$objects.Peek().Kind-cne'object'){throw 'INVALID'}
                # Prefix prevents date-like property names becoming DateTime.
                $key=(ConvertFrom-Json -InputObject ('{"name":"X'+$token.Substring(1)+'}')).name.Substring(1)
                if(-not$objects.Peek().Names.Add($key)){throw 'INVALID'}
            }
            if($objects.Count-gt16){throw 'INVALID'}
        }
        if($objects.Count-ne0){throw 'INVALID'}
        $jsonOptions=@{InputObject=$text}
        if((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')){$jsonOptions.DateKind='String'}
        $record=ConvertFrom-Json @jsonOptions
        if($record-isnot[pscustomobject]){throw 'INVALID'}
        $required=@('schema_version','status','publication_state','remote_sync_attempted','production_mutation','real_line_sent','worker_deployed','run_id','transaction_id','bundle_sha256','error_type','recorded_utc')
        $optional=@('failed_phase','rollback_failed_phase','rollback_error_type','reconciliation')
        $names=@($record.PSObject.Properties.Name)
        foreach($name in $required){if($names-cnotcontains$name){throw 'INVALID'}}
        foreach($name in $names){if(($required+$optional)-cnotcontains$name){throw 'INVALID'}}
        if(-not($record.schema_version-is[int]-or$record.schema_version-is[long])-or$record.schema_version-ne1-or
           $record.status-isnot[string]-or$record.status-cnotin@('PASS','FAIL')-or
           $record.publication_state-isnot[string]-or$record.publication_state-cnotin@('NOT_ATTEMPTED','UNKNOWN','COMMITTED','FINALIZED','ROLLED_BACK','NOT_COMMITTED')-or
           $record.remote_sync_attempted-isnot[bool]-or
           ($null-ne$record.production_mutation-and$record.production_mutation-isnot[bool])-or
           $record.real_line_sent-isnot[bool]-or$record.real_line_sent-or$record.worker_deployed-isnot[bool]-or$record.worker_deployed){throw 'INVALID'}
        foreach($name in @('run_id','transaction_id','bundle_sha256','error_type','recorded_utc')+@($optional|Where-Object{$_-cne'reconciliation'-and$names-ccontains$_})){
            if($record.$name-isnot[string]-or$record.$name.Length-gt128){throw 'INVALID'}
        }
        if($names-ccontains'reconciliation'-and$record.reconciliation-isnot[pscustomobject]){throw 'INVALID'}
        if(($record.status-ceq'PASS')-ne($record.publication_state-ceq'FINALIZED')){throw 'INVALID'}
        if($record.remote_sync_attempted){
            if($record.publication_state-ceq'NOT_ATTEMPTED'-or
               $record.transaction_id-cnotmatch'^[0-9a-f]{32}$'-or$record.run_id-cnotmatch'^\d{8}T\d{6}Z-[0-9a-f]{12}$'-or
               $record.bundle_sha256-cnotmatch'^[0-9a-f]{64}$'-or
               ($record.production_mutation-is[bool]-and-not$record.production_mutation)-or
               ($record.publication_state-cin@('COMMITTED','FINALIZED','ROLLED_BACK')-and$record.production_mutation-ne$true)){throw 'INVALID'}
        } elseif($record.publication_state-cne'NOT_ATTEMPTED'-or$record.production_mutation-isnot[bool]-or$record.production_mutation){throw 'INVALID'}
        # Historical recorded_utc is retained, never treated as source freshness.
        return [pscustomobject]@{Bytes=$bytes;Sha256=$digest;Record=$record}
    } catch {throw 'V213_REFRESH_JOURNAL_INVALID'}
    finally {if($null-ne$stream){$stream.Dispose()};if($null-ne$hasher){$hasher.Dispose()}}
}
function Test-V213RefreshAck($Ack,$Record,[string]$Action) {
    if($Ack.transaction_id-isnot[string]-or$Ack.run_id-isnot[string]-or$Ack.status-isnot[string]-or
       $Ack.transaction_id-cne$Record.transaction_id-or$Ack.run_id-cne$Record.run_id){throw 'V213_REFRESH_ACK_IDENTITY_MISMATCH'}
    switch($Action){
        'Commit' {
            # New v213-stored-snapshot-v1 commit: 13 logical objects plus the seal,
            # not the seven upload payloads. Replay is not a new publication.
            $replay=$Ack.PSObject.Properties['idempotent_replay']
            if($Ack.status-cne'accepted'-or$Ack.pointer_written_last-isnot[bool]-or$Ack.pointer_written_last-ne$true-or
               -not($Ack.object_count-is[int]-or$Ack.object_count-is[long])-or$Ack.object_count-ne14-or
               -not($Ack.objects_read_back-is[int]-or$Ack.objects_read_back-is[long])-or
               $Ack.objects_read_back-ne$Ack.object_count-or$Ack.rollback_available-isnot[bool]-or$Ack.rollback_available-ne$true-or
               $null-eq$replay-or$replay.Value-isnot[bool]-or$replay.Value-ne$false){throw 'V213_REFRESH_READBACK_UNPROVEN'}
        }
        'Finalize' {if($Ack.status-cne'finalized'-or$Ack.rollback_handle_deleted-isnot[bool]-or$Ack.rollback_handle_deleted-ne$true){throw 'V213_REFRESH_FINALIZE_UNPROVEN'}}
        'Rollback' {if($Ack.status-cne'not_committed'-and($Ack.status-cne'rolled_back'-or$Ack.exact_pointer_restored-isnot[bool]-or$Ack.exact_pointer_restored-ne$true)){throw 'V213_REFRESH_ROLLBACK_UNPROVEN'}}
    }
}
function Invoke-V213SealedRefresh {
    param([string]$ProjectRoot,[string]$LocalConfigPath,[string]$ResultPath='',[string]$BundlePath='')
    $bundle=Join-Path $ProjectRoot 'data/cache/v213_activation_bundle_upload.json'
    if($BundlePath-and[IO.Path]::GetFullPath($BundlePath)-ine[IO.Path]::GetFullPath($bundle)){throw 'V213_REFRESH_CANONICAL_BUNDLE_REQUIRED'}
    $journalRoot=Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/status/sealed-publication'
    New-Item -ItemType Directory -Force $journalRoot|Out-Null
    if(-not$ResultPath){$ResultPath=Join-Path $journalRoot ([guid]::NewGuid().ToString('N')+'.json')}
    if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ResultPath))-ine[IO.Path]::GetFullPath($journalRoot)-or[IO.Path]::GetExtension($ResultPath)-ine'.json'){throw 'V213_REFRESH_JOURNAL_SCOPE_INVALID'}
    if(Test-Path -LiteralPath $ResultPath){throw 'V213_REFRESH_JOURNAL_ALREADY_EXISTS'}
    $details=$ResultPath+'.details'
    New-Item -ItemType Directory $details -ErrorAction Stop|Out-Null
    $record=[ordered]@{schema_version=1;status='FAIL';publication_state='NOT_ATTEMPTED';remote_sync_attempted=$false;production_mutation=$false;real_line_sent=$false;worker_deployed=$false;run_id='';transaction_id='';bundle_sha256='';error_type='';recorded_utc=[DateTimeOffset]::UtcNow.ToString('o')}
    $held=$false; $committed=$false
    # Fixed phase identifiers only: never persist exception messages, URLs or credentials.
    $phase='LOCK'
    $record.failed_phase='';$record.rollback_failed_phase='';$record.rollback_error_type=''
    try {
        [void](Enter-V213OperationLock -Owner 'sealed-refresh' -TimeoutSeconds 0);$held=$true
        $phase='JOURNAL_CHECK'
        foreach($previous in Get-ChildItem -LiteralPath $journalRoot -File -Filter '*.json'){
            $old=(Read-V213RefreshJournal $previous.FullName).Record
            if($old.remote_sync_attempted-and$old.publication_state-notin@('FINALIZED','ROLLED_BACK','NOT_COMMITTED')){throw 'V213_REFRESH_UNRESOLVED_JOURNAL'}
        }
        $phase='BUNDLE_VALIDATION'
        $document=Get-Content -LiteralPath $bundle -Raw -Encoding utf8|ConvertFrom-Json
        $record.run_id=[string]$document.run_id;$record.transaction_id=[string]$document.transaction_id
        if($record.run_id-cnotmatch'^\d{8}T\d{6}Z-[0-9a-f]{12}$'-or$record.transaction_id-cnotmatch'^[0-9a-f]{32}$'){throw 'V213_REFRESH_BUNDLE_IDENTITY_INVALID'}
        $sealed=Join-Path $details 'sealed-bundle.json'
        $record.bundle_sha256=(Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
        $phase='PREFLIGHT'
        & (Join-Path $ProjectRoot 'activate-v213-seven-field-schedule.ps1') -ProjectRoot $ProjectRoot -PreflightOnly -FieldLocale bilingual
        if($LASTEXITCODE-ne0){throw 'V213_REFRESH_PREFLIGHT_FAILED'}
        if((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()-cne$record.bundle_sha256){throw 'V213_REFRESH_BUNDLE_CHANGED_AFTER_PREFLIGHT'}
        Copy-Item -LiteralPath $bundle -Destination $sealed
        if((Get-FileHash -LiteralPath $sealed -Algorithm SHA256).Hash.ToLowerInvariant()-cne$record.bundle_sha256){throw 'V213_REFRESH_SEALED_COPY_MISMATCH'}
        $phase='AUTH_CHECK'
        $wrangler=Join-Path $ProjectRoot 'cloud/node_modules/.bin/wrangler.cmd'
        $auth=(& $wrangler whoami 2>$null|Out-String)
        if($LASTEXITCODE-ne0){throw 'V213_REFRESH_READ_ONLY_AUTH_FAILED'}
        $auth=$null
        $sync=Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1'
        $record.remote_sync_attempted=$true;$record.production_mutation=$null;$record.publication_state='UNKNOWN'
        Save-V213RefreshJournal $record $ResultPath
        $ackPath=Join-Path $details 'commit.json'
        $phase='COMMIT_REQUEST'
        & $sync -Action Commit -ProjectRoot $ProjectRoot -BundlePath $sealed -ExpectedBundleSha256 $record.bundle_sha256 -LocalConfigPath $LocalConfigPath -ResultPath $ackPath
        if($LASTEXITCODE-ne0){throw 'V213_REFRESH_COMMIT_FAILED'}
        $phase='COMMIT_ACK'
        $ack=Get-Content -LiteralPath $ackPath -Raw -Encoding utf8|ConvertFrom-Json
        Test-V213RefreshAck $ack $record 'Commit'
        $committed=$true;$record.production_mutation=$true;$record.publication_state='COMMITTED'
        Save-V213RefreshJournal $record $ResultPath
        $ackPath=Join-Path $details 'finalize.json'
        $phase='FINALIZE_REQUEST'
        & $sync -Action Finalize -ProjectRoot $ProjectRoot -LocalConfigPath $LocalConfigPath -TransactionId $record.transaction_id -RunId $record.run_id -ResultPath $ackPath
        if($LASTEXITCODE-ne0){throw 'V213_REFRESH_FINALIZE_FAILED'}
        $phase='FINALIZE_ACK'
        $ack=Get-Content -LiteralPath $ackPath -Raw -Encoding utf8|ConvertFrom-Json
        Test-V213RefreshAck $ack $record 'Finalize'
        $record.publication_state='FINALIZED';$record.status='PASS'
    } catch {
        $record.failed_phase=$phase
        $record.error_type=$_.Exception.GetType().Name
        if($record.remote_sync_attempted){
            try {
                $ackPath=Join-Path $details 'rollback.json'
                $phase='ROLLBACK_REQUEST'
                & $sync -Action Rollback -ProjectRoot $ProjectRoot -LocalConfigPath $LocalConfigPath -TransactionId $record.transaction_id -RunId $record.run_id -ResultPath $ackPath
                if($LASTEXITCODE-ne0){throw 'V213_REFRESH_ROLLBACK_FAILED'}
                $phase='ROLLBACK_ACK'
                $ack=Get-Content -LiteralPath $ackPath -Raw -Encoding utf8|ConvertFrom-Json
                Test-V213RefreshAck $ack $record 'Rollback'
                $record.publication_state=([string]$ack.status).ToUpperInvariant()
                if($ack.status-ceq'rolled_back'){$record.production_mutation=$true}
                # not_committed proves no active pointer for this run, not zero KV writes.
            } catch {
                $record.rollback_failed_phase=$phase
                $record.rollback_error_type=$_.Exception.GetType().Name
                $record.publication_state='UNKNOWN';$record.production_mutation=$(if($committed){$true}else{$null})
            }
        }
        throw 'V213_SEALED_REFRESH_FAILED; inspect_local_publication_journal=true'
    } finally {
        try {Save-V213RefreshJournal $record $ResultPath} finally {if($held){Exit-V213OperationLock}}
    }
    return [pscustomobject]$record
}

function Resolve-V213SealedRefreshJournal {
    param([string]$ProjectRoot,[string]$JournalPath,[string]$LocalConfigPath,
          [switch]$ConfirmRollbackReconciliation)
    if(-not$ConfirmRollbackReconciliation){throw 'V213_RECONCILE_EXPLICIT_CONFIRMATION_REQUIRED'}
    $root=[IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'InvestorIntelligence/status/sealed-publication'))
    if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($JournalPath))-ine$root-or[IO.Path]::GetExtension($JournalPath)-ine'.json'){throw 'V213_RECONCILE_JOURNAL_SCOPE_INVALID'}
    $held=$false
    try {
        [void](Enter-V213OperationLock -Owner 'authorized-journal-reconciliation' -TimeoutSeconds 0);$held=$true
        $snapshot=Read-V213RefreshJournal $JournalPath
        $original=$snapshot.Bytes;$digest=$snapshot.Sha256;$record=$snapshot.Record
        if($record.status-cne'FAIL'-or$record.remote_sync_attempted-isnot[bool]-or-not$record.remote_sync_attempted-or
           $record.publication_state-notin@('UNKNOWN','COMMITTED')-or
           $record.transaction_id-cnotmatch'^[0-9a-f]{32}$'-or$record.run_id-cnotmatch'^\d{8}T\d{6}Z-[0-9a-f]{12}$'){throw 'V213_RECONCILE_STATE_INVALID'}
        $history=Join-Path $root 'reconciliation-history'
        New-Item -ItemType Directory -Force -Path $history|Out-Null
        $archive=Join-Path $history ($digest+'.original.json')
        if(-not(Test-Path -LiteralPath $archive)){[IO.File]::WriteAllBytes($archive,$original)}
        if((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()-cne$digest){throw 'V213_RECONCILE_ARCHIVE_MISMATCH'}
        $ackPath=Join-Path $history ([guid]::NewGuid().ToString('N')+'.ack.json')
        # Reject a changed journal before the mutating transport, not only after it.
        # Rechecking a hash is not a durable identity/participant lock or ABA proof.
        if((Get-FileHash -LiteralPath $JournalPath -Algorithm SHA256).Hash.ToLowerInvariant()-cne$digest){throw 'V213_RECONCILE_JOURNAL_CHANGED'}
        # Explicitly mutating recovery control, not a read-only status request.
        # The existing signed server operation either proves not_committed or
        # restores the exact previous pointer; never commit/replay a stale bundle.
        $global:LASTEXITCODE=0
        & (Join-Path $ProjectRoot 'sync-v213-activation-bundle.ps1') -Action Rollback -ProjectRoot $ProjectRoot -LocalConfigPath $LocalConfigPath -TransactionId $record.transaction_id -RunId $record.run_id -ResultPath $ackPath | Out-Null
        if($LASTEXITCODE-ne0){throw 'V213_RECONCILE_TRANSPORT_FAILED'}
        $ack=Get-Content -LiteralPath $ackPath -Raw -Encoding utf8|ConvertFrom-Json
        Test-V213RefreshAck $ack $record 'Rollback'
        if((Get-FileHash -LiteralPath $JournalPath -Algorithm SHA256).Hash.ToLowerInvariant()-cne$digest){throw 'V213_RECONCILE_JOURNAL_CHANGED'}
        $record.publication_state=([string]$ack.status).ToUpperInvariant()
        if($ack.status-ceq'rolled_back'){$record.production_mutation=$true}
        # Preserve FAIL, original timestamps/error and unknown mutation evidence.
        $record|Add-Member -Force -NotePropertyName reconciliation -NotePropertyValue ([ordered]@{
            reconciled_at=[DateTimeOffset]::UtcNow.ToString('o');action='Rollback';status=$ack.status
            original_sha256=$digest;original_archive=$archive;acknowledgement=$ackPath
        })
        Save-V213RefreshJournal $record $JournalPath
        return [pscustomobject]@{status='RECONCILED';publication_state=$record.publication_state;historical_status=$record.status;original_preserved=$true}
    } finally {if($held){Exit-V213OperationLock}}
}
