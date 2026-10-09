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

namespace InvestorIntelligence
{
    static class Program
    {
        const string Version = "2.1.3";
        const string Revision = "ModelProfile-V1-Development";
        static string PreferredModel {
            get { var profile = LoadModelProfile(); return profile == null ? "" : (string)profile["model"]; }
        }

        static string ProfileTestConfigRoot = null;

        static string ModelProfilePath {
            get { return Path.Combine(ConfigRoot, "v213-model-profile-v1.json"); }
        }

        static Dictionary<string, object> ParseModelProfile(string raw) {
            if (raw == null || raw.Length > 4096) throw new InvalidOperationException("MODEL_PROFILE_INVALID");
            var profile = new JavaScriptSerializer().DeserializeObject(raw) as Dictionary<string, object>;
            string[] fields = { "schema_version", "model", "enable_thinking", "reasoning_effort", "max_output_tokens", "smoke_output_tokens", "timeout_ms" };
            if (profile == null || profile.Count != fields.Length || fields.Any(k => !profile.ContainsKey(k)) ||
                System.Text.RegularExpressions.Regex.Matches(raw, "\"(?:[^\"\\\\]|\\\\.)*\"\\s*:").Count != fields.Length)
                throw new InvalidOperationException("MODEL_PROFILE_INVALID");
            if (!(profile["schema_version"] is int) || (int)profile["schema_version"] != 1 ||
                !(profile["model"] is string) || !System.Text.RegularExpressions.Regex.IsMatch((string)profile["model"], @"\A[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}\z") ||
                !(profile["enable_thinking"] is bool) || !(profile["reasoning_effort"] is string))
                throw new InvalidOperationException("MODEL_PROFILE_INVALID");
            string effort = (string)profile["reasoning_effort"];
            if (!(new [] { "none", "minimal", "low", "medium", "high", "xhigh", "max" }).Contains(effort) ||
                (bool)profile["enable_thinking"] == (effort == "none")) throw new InvalidOperationException("MODEL_PROFILE_INVALID");
            foreach (string key in new [] { "max_output_tokens", "smoke_output_tokens", "timeout_ms" }) {
                int low = key == "timeout_ms" ? 1000 : 1;
                int high = key == "timeout_ms" ? 20000 : 8192;
                if (!(profile[key] is int) || (int)profile[key] < low || (int)profile[key] > high) throw new InvalidOperationException("MODEL_PROFILE_INVALID");
            }
            if ((int)profile["smoke_output_tokens"] > (int)profile["max_output_tokens"]) throw new InvalidOperationException("MODEL_PROFILE_INVALID");
            return profile;
        }

        static string ModelProfileHash(Dictionary<string, object> profile) {
            string[] keys = { "schema_version", "model", "enable_thinking", "reasoning_effort", "max_output_tokens", "smoke_output_tokens", "timeout_ms" };
            string json = new JavaScriptSerializer().Serialize(keys.Select(k => profile[k]).ToArray());
            using (var hash = System.Security.Cryptography.SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(json))).Replace("-", "").ToLowerInvariant();
        }

        static int ModelProfileSelfTest(bool exerciseUi = false) {
            var serializer = new JavaScriptSerializer();
            var profile = new Dictionary<string, object> {
                { "schema_version", 1 }, { "model", "synthetic-model-a" }, { "enable_thinking", true },
                { "reasoning_effort", "xhigh" }, { "max_output_tokens", 1024 }, { "smoke_output_tokens", 128 }, { "timeout_ms", 18000 }
            };
            var boundary = new Dictionary<string, object>(profile); boundary["model"] = new string('x', 200);
            ParseModelProfile(serializer.Serialize(boundary)); boundary["model"] = new string('x', 201);
            try { ParseModelProfile(serializer.Serialize(boundary)); return 65; } catch (InvalidOperationException) { }
            string raw = serializer.Serialize(profile);
            if (ModelProfileHash(ParseModelProfile(raw)) != "2bea7c8ce0f160ea609ddf82c7f34631a6841f9a939debdb0a663444b5307d19") return 58;
            foreach (var change in new Dictionary<string, object> { { "schema_version", true }, { "model", "bad\nmodel" }, { "enable_thinking", "true" }, { "reasoning_effort", "none" }, { "max_output_tokens", 8193 }, { "smoke_output_tokens", 1025 }, { "timeout_ms", 20001 }, { "extra", "unreviewed" } }) {
                var invalid = new Dictionary<string, object>(profile); invalid[change.Key] = change.Value;
                try { ParseModelProfile(serializer.Serialize(invalid)); return 59; } catch (InvalidOperationException) { }
            }
            try { ParseModelProfile(raw.Substring(0, raw.Length - 1) + ",\"model\":\"hidden\"}"); return 60; } catch (InvalidOperationException) { }
            profile["model"] = "other/model-v2"; profile["enable_thinking"] = false; profile["reasoning_effort"] = "none";
            if ((string)ParseModelProfile(serializer.Serialize(profile))["model"] != "other/model-v2") return 61;
            string previous = Environment.GetEnvironmentVariable("V213_MODEL_PROFILE_JSON");
            string isolated = Path.Combine(Path.GetTempPath(), "ii-profile-selftest-" + Guid.NewGuid().ToString("N"));
            try {
                ProfileTestConfigRoot = isolated;
                Environment.SetEnvironmentVariable("V213_MODEL_PROFILE_JSON", serializer.Serialize(profile));
                if (exerciseUi) {
                    var context = System.Threading.SynchronizationContext.Current;
                    try {
                        using (var form = new MainForm(false)) {
                            int result = form.ThinkingUiSelfTest(isolated);
                            if (result != 0) return result;
                        }
                    } finally { System.Threading.SynchronizationContext.SetSynchronizationContext(context); }
                }
                string before = ModelProfileHash(profile);
                foreach (string model in new [] { "third/model-v3", "fourth/model-v4" }) {
                    SaveSelection(model, "http://127.0.0.1:8080", new List<string> { model }, "synthetic-self-test");
                    var persisted = ParseModelProfile(File.ReadAllText(ModelProfilePath, Encoding.UTF8));
                    if (LoadSelection().Model != model || (string)persisted["model"] != model || (bool)persisted["enable_thinking"] || (string)persisted["reasoning_effort"] != "none") return 62;
                    var selection = serializer.DeserializeObject(File.ReadAllText(SelectionPath, Encoding.UTF8)) as Dictionary<string, object>;
                    if ((string)selection["model_profile_sha256"] != ModelProfileHash(persisted) || (bool)selection["model_profile_qualified"] || before == ModelProfileHash(persisted)) return 63;
                }
                string probe = Path.Combine(isolated, "profile-child.ps1");
                File.WriteAllText(probe, "$p=$env:V213_MODEL_PROFILE_JSON|ConvertFrom-Json; if($p.model -cne 'fourth/model-v4' -or $p.enable_thinking -ne $false -or $p.reasoning_effort -cne 'none'){exit 1}; Write-Output 'V213_MODEL_PROFILE_CHILD = PASS'; exit 0", new UTF8Encoding(false));
                if (RunPowerShellCli(probe, "") != 0) return 64;
            } finally {
                ProfileTestConfigRoot = null;
                Environment.SetEnvironmentVariable("V213_MODEL_PROFILE_JSON", previous);
                if (Directory.Exists(isolated)) Directory.Delete(isolated, true);
            }
            return 0;
        }

        static Dictionary<string, object> LoadModelProfile() {
            string raw = Environment.GetEnvironmentVariable("V213_MODEL_PROFILE_JSON");
            if (raw == null) {
                string path = File.Exists(ModelProfilePath) ? ModelProfilePath : Path.Combine(Root, "config", "v213-model-profile-v1.json");
                if (!File.Exists(path)) return null; // legacy installations without a profile
                if (new FileInfo(path).Length > 4096) throw new InvalidOperationException("MODEL_PROFILE_INVALID");
                raw = File.ReadAllText(path, Encoding.UTF8);
            }
            try { return ParseModelProfile(raw); }
            catch { throw new InvalidOperationException("MODEL_PROFILE_INVALID"); }
        }

        const string DefaultLlamaBase = "http://127.0.0.1:8080"; // ninfer; TabbyAPI :5000 removed 2026-09-27
        const int MaxModelCatalogBytes = 1024 * 1024;

        static string LastPowerShellSummary = "";
        static volatile string LastPowerShellLiveLine = "";

        sealed class CaptureState
        {
            public readonly object Sync = new object();
            public readonly StringBuilder Tail = new StringBuilder();
            public readonly StreamWriter Writer;
            public bool Open = true;

            public CaptureState(StreamWriter writer)
            {
                Writer = writer;
            }
        }

        sealed class ModelSelection
        {
            public string Model = "";
            public string LlamaBaseUrl = "";
            public string BindingJson = null;
        }

        static string BindingPath { get { return Path.Combine(ConfigRoot, "v213-runtime-binding-v1.json"); } }
        static string CanonicalStrataRoot(string raw, bool inputBoundary = false) {
            var m = Regex.Match(raw ?? "", inputBoundary ? @"\Ahttp://127\.0\.0\.1:([1-9][0-9]{0,4})(?:/v1)?/?\z" : @"\Ahttp://127\.0\.0\.1:([1-9][0-9]{0,4})\z");
            int port;
            if (!m.Success || !Int32.TryParse(m.Groups[1].Value, out port) || port < 1 || port > 65535) throw new InvalidOperationException("BINDING_ENDPOINT_INVALID");
            return "http://127.0.0.1:" + port;
        }
        static Dictionary<string, object> ParseRuntimeBinding(string raw, Dictionary<string, object> profile) {
            string[] fields = { "schema_version", "engine", "base_url", "model", "model_profile_sha256", "qualification" };
            if (raw == null || Encoding.UTF8.GetByteCount(raw) > 4096) throw new InvalidOperationException("BINDING_INVALID");
            var value = new JavaScriptSerializer().DeserializeObject(raw) as Dictionary<string, object>;
            if (value == null || value.Count != 6 || fields.Any(k => !value.ContainsKey(k)) || Regex.Matches(raw, "\"(?:[^\"\\\\]|\\\\.)*\"\\s*:").Count != 6
                || !(value["schema_version"] is int) || (int)value["schema_version"] != 1 || !Object.Equals(value["engine"], "strata")
                || !Object.Equals(value["qualification"], "UNQUALIFIED") || !(value["base_url"] is string) || !(value["model"] is string)
                || !SafeModelId((string)value["model"]) || profile == null || !Object.Equals(value["model"], profile["model"])
                || !Object.Equals(value["model_profile_sha256"], ModelProfileHash(profile))) throw new InvalidOperationException("BINDING_INVALID");
            CanonicalStrataRoot((string)value["base_url"]);
            return value;
        }
        static string RuntimeBindingHash(Dictionary<string, object> value) {
            string[] fields = { "schema_version", "engine", "base_url", "model", "model_profile_sha256", "qualification" };
            string raw = new JavaScriptSerializer().Serialize(fields.Select(k => value[k]).ToArray());
            using (var hash = System.Security.Cryptography.SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(Encoding.ASCII.GetBytes(raw))).Replace("-", "").ToLowerInvariant();
        }
        static Dictionary<string, object> LoadRuntimeBinding() {
            string env = Environment.GetEnvironmentVariable("V213_RUNTIME_BINDING_JSON");
            bool saved = File.Exists(BindingPath) || Directory.Exists(BindingPath);
            if (env == null && !saved) return null;
            var profile = LoadModelProfile();
            if (File.Exists(ModelProfilePath) || Directory.Exists(ModelProfilePath)) {
                if (new FileInfo(ModelProfilePath).Length > 4096 || profile == null ||
                    ModelProfileHash(ParseModelProfile(File.ReadAllText(ModelProfilePath, Encoding.UTF8))) != ModelProfileHash(profile))
                    throw new InvalidOperationException("BINDING_SAVED_PROFILE_CONFLICT");
            }
            Dictionary<string, object> value = env == null ? null : ParseRuntimeBinding(env, profile);
            if (saved) {
                if (new FileInfo(BindingPath).Length > 4096) throw new InvalidOperationException("BINDING_INVALID");
                var persisted = ParseRuntimeBinding(File.ReadAllText(BindingPath, Encoding.UTF8), profile);
                if (value != null && RuntimeBindingHash(value) != RuntimeBindingHash(persisted)) throw new InvalidOperationException("BINDING_SOURCE_CONFLICT");
                value = persisted;
            }
            foreach (string key in new [] { "II_LOCAL_LLM_MODEL", "II_LLAMA_BASE_URL" }) {
                string supplied = Environment.GetEnvironmentVariable(key);
                if (supplied != null && (key == "II_LLAMA_BASE_URL" ? CanonicalStrataRoot(supplied, true) : supplied) != (string)value[key == "II_LLAMA_BASE_URL" ? "base_url" : "model"]) throw new InvalidOperationException("BINDING_ENV_CONFLICT");
            }
            return value;
        }
        static string ExistingBindingPython() {
            string python = Environment.GetEnvironmentVariable("PROJECT_PYTHON");
            if (String.IsNullOrWhiteSpace(python)) python = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "InvestorIntelligence", "Runtime", "python-3.12.10", "python.exe");
            if (!File.Exists(python)) throw new InvalidOperationException("BINDING_PYTHON_PREREQUISITE_UNAVAILABLE");
            return python;
        }
        // Ownership is PROVENANCE, never value equality. A key is launcher-owned only
        // when this launcher introduced it while the key was absent, or replaced a
        // value it still owns and that nobody changed. Externally supplied intent
        // (byte-identical, semantically equal, partial or different) is never adopted
        // by an unchanged save/Check/Use, so a later differing save or removal still
        // hands it to the shared helper, which refuses until the external source is
        // removed outside this path. Only owned keys are cleared from a child.
        static readonly string[] IntentEnvironmentKeys = { "V213_MODEL_PROFILE_JSON", "V213_RUNTIME_BINDING_JSON" };
        static readonly Dictionary<string, string> OwnedIntentEnvironment = new Dictionary<string, string>();
        // ONE lock around every complete ownership read/reconcile -> child invocation -> post-child adoption window (the original offline
        // save, removal and the registry's manual verified selection) and around each mutation of the owned map. Monitor is reentrant on the
        // same thread. A bounded wait keeps the UI thread from hanging forever; the caller then sees INTENT_BUSY and nothing changes.
        static readonly object IntentLock = new object();
        static void WithIntentLock(Action work) {
            if (!System.Threading.Monitor.TryEnter(IntentLock, 40000)) throw new InvalidOperationException("INTENT_BUSY");
            try { work(); } finally { System.Threading.Monitor.Exit(IntentLock); }
        }
        static T WithIntentLock<T>(Func<T> work) {
            if (!System.Threading.Monitor.TryEnter(IntentLock, 40000)) throw new InvalidOperationException("INTENT_BUSY");
            try { return work(); } finally { System.Threading.Monitor.Exit(IntentLock); }
        }
        static void ReconcileOwnedIntentEnvironment() {
            // An owned value that was externally replaced or removed loses ownership BEFORE any mutation.
            lock (IntentLock) {
                foreach (string key in OwnedIntentEnvironment.Keys.ToList())
                    if (Environment.GetEnvironmentVariable(key) != OwnedIntentEnvironment[key]) OwnedIntentEnvironment.Remove(key);
            }
        }
        static void ClearOwnedIntentEnvironment(ProcessStartInfo start) {
            lock (IntentLock) {
                ReconcileOwnedIntentEnvironment();
                foreach (var entry in OwnedIntentEnvironment) start.EnvironmentVariables.Remove(entry.Key);
            }
        }
        static int RunBindingHelper(string arguments, object request, bool clearOwned) {
            var start = new ProcessStartInfo { FileName=ExistingBindingPython(),
                Arguments="\"" + Path.Combine(Root, "scripts", "v213_model_profile.py") + "\" " + arguments,
                UseShellExecute=false, CreateNoWindow=true, RedirectStandardInput=true, RedirectStandardOutput=true, RedirectStandardError=true };
            if (clearOwned) ClearOwnedIntentEnvironment(start);
            using (var process = Process.Start(start)) {
                if (request != null) process.StandardInput.Write(new JavaScriptSerializer().Serialize(request));
                process.StandardInput.Close();
                // Helper emits only bounded sanitized results; never echo response/error bodies.
                var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(35000)) { process.Kill(); throw new InvalidOperationException("BINDING_OPERATION_TIMEOUT"); }
                if (!stdout.Wait(1000) || !stderr.Wait(1000) || stdout.Result.Length > 16384 || stderr.Result.Length > 4096)
                    throw new InvalidOperationException("BINDING_OPERATION_UNAVAILABLE");
                return process.ExitCode;
            }
        }
        static void RemoveExplicitBinding() { WithIntentLock(RemoveExplicitBindingLocked); }
        static void RemoveExplicitBindingLocked() {
            ReconcileOwnedIntentEnvironment();
            // External V213_RUNTIME_BINDING_JSON / II_* intent is NOT cleared here: the helper refuses it.
            if (RunBindingHelper("--remove-binding", null, true) != 0) throw new InvalidOperationException("BINDING_REMOVE_UNAVAILABLE");
            foreach (var entry in OwnedIntentEnvironment)
                if (Environment.GetEnvironmentVariable(entry.Key) == entry.Value) Environment.SetEnvironmentVariable(entry.Key, null);
            OwnedIntentEnvironment.Clear();
        }
        static void SaveExplicitBinding(string model, string endpoint, string effort, int output, int smoke, int timeout) {
            WithIntentLock(delegate { SaveExplicitBindingLocked(model, endpoint, effort, output, smoke, timeout); });
        }
        // The original OFFLINE save (no request is sent), now one complete window under IntentLock.
        static void SaveExplicitBindingLocked(string model, string endpoint, string effort, int output, int smoke, int timeout) {
            var profile = LoadModelProfile();
            if (profile == null) throw new InvalidOperationException("MODEL_PROFILE_REQUIRED");
            profile["model"] = model; profile["enable_thinking"] = effort != "none"; profile["reasoning_effort"] = effort;
            profile["max_output_tokens"] = output; profile["smoke_output_tokens"] = smoke; profile["timeout_ms"] = timeout;
            var serializer = new JavaScriptSerializer(); ParseModelProfile(serializer.Serialize(profile));
            LoadSelection(); // saved/env/profile/selection conflicts fail BEFORE writes
            // Provenance is decided BEFORE the helper runs: only a key that is absent now or still
            // launcher-owned and unchanged may be (re)written after the save.
            ReconcileOwnedIntentEnvironment();
            var writable = new HashSet<string>(IntentEnvironmentKeys.Where(key =>
                Environment.GetEnvironmentVariable(key) == null || OwnedIntentEnvironment.ContainsKey(key)));
            var envBefore = IntentEnvironmentKeys.ToDictionary(key => key, key => Environment.GetEnvironmentVariable(key));
            var ownedBefore = new HashSet<string>(OwnedIntentEnvironment.Keys);
            var request = new Dictionary<string, object> { {"root", Root}, {"base_url", CanonicalStrataRoot(endpoint, true)}, {"model", model}, {"profile", profile} };
            if (RunBindingHelper("--save-binding-stdin", request, true) != 0) throw new InvalidOperationException("BINDING_SAVE_UNAVAILABLE");
            foreach (var entry in new Dictionary<string, string> {
                {"V213_MODEL_PROFILE_JSON", serializer.Serialize(profile)}, {"V213_RUNTIME_BINDING_JSON", File.ReadAllText(BindingPath, Encoding.UTF8)} }) {
                // Pre-existing external intent keeps its bytes and stays external (not owned, not overwritten). A set captured before
                // the child ran is not authority: the key must still be unchanged and, if it was owned, still owned.
                ReconcileOwnedIntentEnvironment();
                if (!writable.Contains(entry.Key) || Environment.GetEnvironmentVariable(entry.Key) != envBefore[entry.Key]
                    || (ownedBefore.Contains(entry.Key) && !OwnedIntentEnvironment.ContainsKey(entry.Key))) continue;
                Environment.SetEnvironmentVariable(entry.Key, entry.Value); OwnedIntentEnvironment[entry.Key] = entry.Value;
            }
        }

        // M1: callers of the shared registry helper scripts/local_model_catalog.py. Same prerequisite rule as the binding helper: an
        // existing interpreter only, no bootstrap or install. Only the bounded sanitized JSON result is parsed; raw output is never shown.
        static string CatalogReason(Dictionary<string, object> result)
        {
            string reason = result.ContainsKey("reason") ? result["reason"] as string : null;
            return reason != null && Regex.IsMatch(reason, @"\A[A-Z][A-Z0-9_]{0,63}\z") ? reason : "CATALOG_OPERATION_UNAVAILABLE";
        }

        static Dictionary<string, object> RunCatalogHelper(string op, Dictionary<string, object> request, bool clearOwned)
        {
            var start = new ProcessStartInfo { FileName = ExistingBindingPython(),
                Arguments = "\"" + Path.Combine(Root, "scripts", "local_model_catalog.py") + "\" --op " + op,
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
            if (clearOwned) ClearOwnedIntentEnvironment(start);
            using (var process = Process.Start(start))
            {
                process.StandardInput.Write(new JavaScriptSerializer().Serialize(request ?? new Dictionary<string, object>()));
                process.StandardInput.Close();
                var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(35000)) { process.Kill(); throw new InvalidOperationException("CATALOG_OPERATION_TIMEOUT"); }
                if (!stdout.Wait(1000) || !stderr.Wait(1000) || stdout.Result.Length > 262144 || stderr.Result.Length > 4096)
                    throw new InvalidOperationException("CATALOG_OPERATION_UNAVAILABLE");
                var result = new JavaScriptSerializer().DeserializeObject(stdout.Result.Trim()) as Dictionary<string, object>;
                if (result == null) throw new InvalidOperationException("CATALOG_OPERATION_UNAVAILABLE");
                if (process.ExitCode != 0 || result.ContainsKey("error")) throw new InvalidOperationException(CatalogReason(result));
                return result;
            }
        }

        // Selection writes REQUEST INTENT only, through the original helper path: the same pre-save conflict check and the same
        // launcher-owned environment provenance as SaveExplicitBinding; external intent is never adopted or cleared. Nothing is
        // started, stopped, loaded or replaced.
        static Dictionary<string, object> RunCatalogSelection(string op, Dictionary<string, object> request)
        {
            return WithIntentLock(delegate { return RunCatalogSelectionLocked(op, request); });
        }

        static Dictionary<string, object> RunCatalogSelectionLocked(string op, Dictionary<string, object> request)
        {
            LoadSelection(); // saved/env/profile/selection conflicts fail BEFORE writes
            ReconcileOwnedIntentEnvironment();
            var writable = new HashSet<string>(IntentEnvironmentKeys.Where(key =>
                Environment.GetEnvironmentVariable(key) == null || OwnedIntentEnvironment.ContainsKey(key)));
            var envBefore = IntentEnvironmentKeys.ToDictionary(key => key, key => Environment.GetEnvironmentVariable(key));
            var ownedBefore = new HashSet<string>(OwnedIntentEnvironment.Keys);
            var result = RunCatalogHelper(op, request, true);
            string scope = result.ContainsKey("scope") ? result["scope"] as string : null;
            if (scope == "VERIFIED_REQUEST_INTENT")
            {
                foreach (var entry in new Dictionary<string, string> {
                    {"V213_MODEL_PROFILE_JSON", File.ReadAllText(ModelProfilePath, Encoding.UTF8)},
                    {"V213_RUNTIME_BINDING_JSON", File.ReadAllText(BindingPath, Encoding.UTF8)} })
                {
                    ReconcileOwnedIntentEnvironment();
                    if (!writable.Contains(entry.Key) || Environment.GetEnvironmentVariable(entry.Key) != envBefore[entry.Key]
                        || (ownedBefore.Contains(entry.Key) && !OwnedIntentEnvironment.ContainsKey(entry.Key))) continue;
                    Environment.SetEnvironmentVariable(entry.Key, entry.Value); OwnedIntentEnvironment[entry.Key] = entry.Value;
                }
            }
            return result;
        }

        sealed class ModelCatalog
        {
            public string BaseUrl = "";
            public readonly List<string> Models = new List<string>();
            public string Error = "";
            public bool AutoDetected;
            public string Chosen = "";  // the model picked automatically (exact, same family or the only one)
            public string Match = "";
        }

        sealed class NamedTunnelSettings
        {
            public string Name = "";
            public string Hostname = "";
            public string ConfigPath = "";
        }

        static string Root
        {
            get { return AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar); }
        }

        static string ConfigRoot
        {
            get
            {
                if (ProfileTestConfigRoot != null) return ProfileTestConfigRoot;
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "InvestorIntelligence", "UserData", "config");
            }
        }

        static string SelectionPath
        {
            get { return Path.Combine(ConfigRoot, "v213-model-selection.json"); }
        }

        static string NamedTunnelPath
        {
            get { return Path.Combine(ConfigRoot, "v213-named-tunnel.json"); }
        }

        static string Tail(string value, int maximum)
        {
            if (String.IsNullOrEmpty(value)) return "";
            return value.Length <= maximum ? value : value.Substring(value.Length - maximum);
        }

        static string UiSafeProgressLine(string line)
        {
            if (String.IsNullOrWhiteSpace(line)) return "";
            string value = line.Trim().Replace("\r", " ").Replace("\n", " ");
            if (
                value.StartsWith("II_STAGE ", StringComparison.Ordinal) ||
                value.StartsWith("II_PROGRESS ", StringComparison.Ordinal) ||
                value.StartsWith("V213_", StringComparison.Ordinal) ||
                value.StartsWith("INVESTOR_INTELLIGENCE_", StringComparison.Ordinal) ||
                value.StartsWith("V2.1.3 SCHEDULED", StringComparison.Ordinal)
            )
            {
                return value.Length <= 145 ? value : value.Substring(0, 142) + "...";
            }
            return "";
        }

        static void AppendTail(StringBuilder tail, string channel, string line)
        {
            tail.Append(channel).Append(" ").AppendLine(line);
            const int keep = 22000;
            if (tail.Length > keep + 5000)
                tail.Remove(0, tail.Length - keep);
        }

        static void RecordCapturedLine(CaptureState state, string channel, string line)
        {
            string safe = "";
            lock (state.Sync)
            {
                if (!state.Open) return;
                state.Writer.Write(DateTime.Now.ToString("HH:mm:ss.fff"));
                state.Writer.Write(" [");
                state.Writer.Write(channel);
                state.Writer.Write("] ");
                state.Writer.WriteLine(line);
                state.Writer.Flush();
                AppendTail(state.Tail, channel, line);
                safe = UiSafeProgressLine(line);
            }
            if (!String.IsNullOrEmpty(safe))
                LastPowerShellLiveLine = safe;
        }

        static void DrainAvailableLines(StreamReader reader, CaptureState state)
        {
            string line;
            while ((line = reader.ReadLine()) != null)
                RecordCapturedLine(state, "OUT", line);
        }

        static string PowerShellLiteral(string value)
        {
            return "'" + value.Replace("'", "''") + "'";
        }

        static string CmdQuoted(string value)
        {
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }

        static bool SafeModelId(string value)
        {
            return !String.IsNullOrWhiteSpace(value) &&
                Regex.IsMatch(value, @"\A[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}\z");
        }

        static bool SafeLoopbackBase(string value)
        {
            Uri uri;
            if (!Uri.TryCreate(value, UriKind.Absolute, out uri)) return false;
            if (uri.Scheme != Uri.UriSchemeHttp || !String.IsNullOrEmpty(uri.UserInfo)) return false;
            if (!(uri.Host.Equals("127.0.0.1", StringComparison.OrdinalIgnoreCase) ||
                  uri.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase))) return false;
            return uri.Port >= 1 && uri.Port <= 65535 && !ProtectedModelPort(uri.Port) &&
                (uri.AbsolutePath == "/" || uri.AbsolutePath == "") &&
                String.IsNullOrEmpty(uri.Query) && String.IsNullOrEmpty(uri.Fragment);
        }

        static List<string> ExtractModelIds(string json)
        {
            var result = new List<string>();
            var serializer = new JavaScriptSerializer();
            object root = serializer.DeserializeObject(json);
            var dictionary = root as Dictionary<string, object>;
            if (dictionary == null || !dictionary.ContainsKey("data")) return result;
            var rows = dictionary["data"] as IEnumerable;
            if (rows == null) return result;

            // UI choices only. The shared Python resolver revalidates the full
            // catalog and actual completion before the bridge can be used.
            var owners = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (object raw in rows)
            {
                var item = raw as Dictionary<string, object>;
                if (item == null || !item.ContainsKey("id")) throw new InvalidOperationException("Invalid model catalog.");
                string id = item["id"] as string;
                if (!SafeModelId(id)) throw new InvalidOperationException("Invalid model identity.");
                var names = new List<string> { id };
                if (item.ContainsKey("aliases"))
                {
                    var aliases = item["aliases"] as object[];
                    if (aliases == null) throw new InvalidOperationException("Invalid model aliases.");
                    foreach (object alias in aliases)
                    {
                        string name = alias as string;
                        if (!SafeModelId(name)) throw new InvalidOperationException("Invalid model alias.");
                        names.Add(name);
                    }
                }
                foreach (string name in names)
                {
                    string owner;
                    if (owners.TryGetValue(name, out owner) && !owner.Equals(id, StringComparison.Ordinal))
                        throw new InvalidOperationException("Ambiguous model catalog alias.");
                    owners[name] = id;
                    if (seen.Add(name)) result.Add(name);
                    if (result.Count > 1024) throw new InvalidOperationException("MODEL_CATALOG_TOO_LARGE");
                }
            }
            return result;
        }

        static string HttpGet(string url)
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Proxy = null;
            request.AllowAutoRedirect = false;
            request.UseDefaultCredentials = false;
            request.KeepAlive = false;
            request.Timeout = 4500;
            request.ReadWriteTimeout = 4500;
            request.Headers[HttpRequestHeader.CacheControl] = "no-cache";

            var clock = Stopwatch.StartNew();
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            using (var bytes = new MemoryStream())
            {
                if ((int)response.StatusCode != 200) throw new InvalidOperationException("MODEL_CATALOG_HTTP_FAILED");
                if (response.ContentLength > MaxModelCatalogBytes) throw new InvalidOperationException("MODEL_CATALOG_TOO_LARGE");
                byte[] buffer = new byte[4096];
                while (true) {
                    int remaining = 4500 - (int)clock.ElapsedMilliseconds;
                    if (remaining <= 0) throw new InvalidOperationException("MODEL_CATALOG_TIMEOUT");
                    if (stream.CanTimeout) stream.ReadTimeout = remaining;
                    int count = stream.Read(buffer, 0, buffer.Length);
                    if (clock.ElapsedMilliseconds > 4500) throw new InvalidOperationException("MODEL_CATALOG_TIMEOUT");
                    if (count == 0) break;
                    if (bytes.Length + count > MaxModelCatalogBytes) throw new InvalidOperationException("MODEL_CATALOG_TOO_LARGE");
                    bytes.Write(buffer, 0, count);
                }
                return new UTF8Encoding(false, true).GetString(bytes.ToArray());
            }
        }

        // Operator request 2026-09-25: follow the local model server when its address or model changes.
        // Loopback only, read-only /models or /v1/models, well-known OpenAI-compatible ports:
        // Strata 8080, Ollama 11434, LM Studio 1234 and common alternates. 5000 (IBKR Client Portal, a broker endpoint with no model
        // catalog) and 8000 (retired System One decider) are never probed, from ANY source: known ports, the live listener union,
        // saved/hinted bases and explicit input all pass ProtectedModelPort.
        static readonly int[] KnownModelPorts = { 8080, 11434, 1234, 5001, 8081 };
        static bool ProtectedModelPort(int port) { return port == 5000 || port == 8000; }

        static List<string> ModelBaseCandidates(string saved, bool includeListeners = false)
        {
            var bases = new List<string>();
            if (!String.IsNullOrEmpty(saved) && SafeLoopbackBase(saved)) bases.Add(saved.TrimEnd('/'));
            bases.Add(DefaultLlamaBase);
            bases.AddRange(KnownModelPorts.Select(port => "http://127.0.0.1:" + port));
            // Operator request 2026-09-26: a model server on any other port is found too (every loopback listener).
            if (includeListeners) bases.AddRange(LoopbackListenerPorts().Select(port => "http://127.0.0.1:" + port));
            return bases.Where(b => !ProtectedModelPort(new Uri(b).Port))
                .Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        static List<int> LoopbackListenerPorts()
        {
            try {
                return System.Net.NetworkInformation.IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners()
                    .Where(e => IPAddress.IsLoopback(e.Address) || e.Address.Equals(IPAddress.Any) || e.Address.Equals(IPAddress.IPv6Any))
                    .Select(e => e.Port).Where(p => p >= 1024 && !ProtectedModelPort(p)).Distinct().OrderBy(p => p).Take(48).ToList();
            } catch { return new List<int>(); }
        }

        // Qwen3.8-27B-EXL3-5.5bpw-v2 -> qwen3.8-27b: the id up to its parameter-count token (same rule as
        // scripts/local_model_endpoint.py); an id without one is its own family.
        static string ModelFamily(string id)
        {
            string[] parts = (id ?? "").Trim().Split('-');
            for (int i = 0; i < parts.Length; i++)
                if (Regex.IsMatch(parts[i], @"\A\d+(\.\d+)?[BbMm]\z")) return String.Join("-", parts.Take(i + 1)).ToLowerInvariant();
            return (id ?? "").Trim().ToLowerInvariant();
        }

        // Exact wanted model, else one served model of the same family, else the only model; null when ambiguous.
        static string[] ChooseModel(List<string> ids, IEnumerable<string> wanted)
        {
            var names = wanted.Where(w => !String.IsNullOrWhiteSpace(w)).ToList();
            foreach (string w in names) {
                string hit = ids.FirstOrDefault(id => id.Equals(w, StringComparison.OrdinalIgnoreCase));
                if (hit != null) return new[] { hit, "exact" };
            }
            foreach (string w in names) {
                var hits = ids.Where(id => ModelFamily(id) == ModelFamily(w)).ToList();
                if (hits.Count == 1) return new[] { hits[0], "family" };
            }
            return ids.Count == 1 ? new[] { ids[0], "only" } : null;
        }

        static List<string> ReadCatalog(string baseUrl)
        {
            foreach (string suffix in new[] { "/models", "/v1/models" })
            {
                try
                {
                    List<string> ids = ExtractModelIds(HttpGet(baseUrl + suffix));
                    if (ids.Count > 0) return ids;
                }
                catch { }
            }
            return null;
        }

        static ModelCatalog DiscoverModels(ModelSelection previous, bool discover = false)
        {
            if ((previous != null && previous.BindingJson != null) || LoadSelection().BindingJson != null)
                throw new InvalidOperationException("EXPLICIT_BINDING_USE_SELECTED_METADATA_CHECK_NO_DISCOVERY");
            var catalog = new ModelCatalog();
            if (previous != null && !String.IsNullOrEmpty(previous.LlamaBaseUrl) && !SafeLoopbackBase(previous.LlamaBaseUrl)) {
                catalog.Error = "MODEL_ROUTER_URL_INVALID";
                return catalog;
            }
            string preferred = PreferredModel;
            string saved = previous != null ? previous.LlamaBaseUrl : "";
            var wanted = new List<string> { previous != null ? previous.Model : "", preferred };
            // Saved address first; then (UI scan only) known local ports and every other loopback listener, read in
            // parallel. The best model match wins (exact, then same family, then the only model), the earlier address
            // on a tie; without any match the first reachable catalog is offered. A changed model leaves the profile
            // unqualified until it is saved and requalified. Explicit command-line checks keep exactly their address.
            var candidates = discover ? ModelBaseCandidates(saved, true)
                : new List<string> { SafeLoopbackBase(saved) ? saved.TrimEnd('/') : DefaultLlamaBase };
            var catalogs = new List<string>[candidates.Count];
            System.Threading.Tasks.Parallel.For(0, candidates.Count, new ParallelOptions { MaxDegreeOfParallelism = 16 },
                i => { catalogs[i] = ReadCatalog(candidates[i]); });
            string firstBase = null, bestBase = null;
            List<string> firstIds = null, bestIds = null;
            string[] best = null;
            var rank = new Dictionary<string, int> { { "exact", 0 }, { "family", 1 }, { "only", 2 } };
            for (int i = 0; i < candidates.Count; i++)
            {
                List<string> ids = catalogs[i];
                if (ids == null) continue;
                if (firstBase == null) { firstBase = candidates[i]; firstIds = ids; }
                string[] choice = ChooseModel(ids, wanted);
                if (choice != null && (best == null || rank[choice[1]] < rank[best[1]])) { best = choice; bestBase = candidates[i]; bestIds = ids; }
            }
            if (firstBase == null)
            {
                catalog.Error = "MODEL_CATALOG_UNAVAILABLE: no local model server answered on the saved address, known ports or other loopback listeners.";
                return catalog;
            }
            if (bestBase != null) { firstBase = bestBase; firstIds = bestIds; catalog.Chosen = best[0]; catalog.Match = best[1]; }
            catalog.BaseUrl = firstBase;
            catalog.AutoDetected = !firstBase.Equals((saved ?? "").TrimEnd('/'), StringComparison.OrdinalIgnoreCase);
            string chosen = catalog.Chosen;
            catalog.Models.AddRange(firstIds.OrderBy(
                id => id.Equals(chosen, StringComparison.OrdinalIgnoreCase) ? "0" + id
                    : id.Equals(preferred, StringComparison.OrdinalIgnoreCase) ? "1" + id : "2" + id,
                StringComparer.OrdinalIgnoreCase));
            return catalog;
        }

        static ModelSelection LoadSelection()
        {
            var binding = LoadRuntimeBinding(); // invalid presence NEVER caught into legacy
            if (binding != null) {
                if (Directory.Exists(SelectionPath)) throw new InvalidOperationException("BINDING_SELECTION_CONFLICT");
                if (File.Exists(SelectionPath)) {
                    if (new FileInfo(SelectionPath).Length > 16384) throw new InvalidOperationException("BINDING_SELECTION_CONFLICT");
                    string raw = File.ReadAllText(SelectionPath, Encoding.UTF8);
                    var selection = new JavaScriptSerializer().DeserializeObject(raw) as Dictionary<string, object>;
                    string[] fields = { "schema_version", "product_version", "engine", "model", "llama_base_url", "runtime_binding_sha256", "model_profile_sha256", "model_profile_qualified", "source" };
                    if (selection == null || selection.Count != fields.Length || fields.Any(k => !selection.ContainsKey(k))
                        || Regex.Matches(raw, "\"(?:[^\"\\\\]|\\\\.)*\"\\s*:").Count != fields.Length
                        || !(selection["schema_version"] is int) || (int)selection["schema_version"] != 2
                        || !Object.Equals(selection["product_version"], "2.1.3") || !Object.Equals(selection["engine"], "strata")
                        || !Object.Equals(selection["model_profile_qualified"], false) || !Object.Equals(selection["source"], "EXPLICIT_OFFLINE_INTENT")
                        || !Object.Equals(selection["model_profile_sha256"], binding["model_profile_sha256"])
                        || !Object.Equals(selection["runtime_binding_sha256"], RuntimeBindingHash(binding))
                        || !Object.Equals(selection["model"], binding["model"])
                        || !Object.Equals(selection["llama_base_url"], binding["base_url"])) throw new InvalidOperationException("BINDING_SELECTION_CONFLICT");
                }
                return new ModelSelection { Model=(string)binding["model"], LlamaBaseUrl=(string)binding["base_url"], BindingJson=new JavaScriptSerializer().Serialize(binding) };
            }
            try
            {
                if (Directory.Exists(SelectionPath)) throw new InvalidOperationException("MODEL_SELECTION_INVALID");
                if (!File.Exists(SelectionPath)) return new ModelSelection();
                if (new FileInfo(SelectionPath).Length > 16384) throw new InvalidOperationException("MODEL_SELECTION_INVALID");
                var serializer = new JavaScriptSerializer();
                var root = serializer.DeserializeObject(
                    File.ReadAllText(SelectionPath, Encoding.UTF8)) as Dictionary<string, object>;
                if (root == null) throw new InvalidOperationException("MODEL_SELECTION_INVALID");
                if (root.ContainsKey("engine") || root.ContainsKey("runtime_binding_sha256")) throw new InvalidOperationException("BINDING_SELECTION_WITHOUT_INTENT");

                return new ModelSelection {
                    Model = !String.IsNullOrEmpty(PreferredModel) ? PreferredModel : (root.ContainsKey("model") ? Convert.ToString(root["model"]) ?? "" : ""),
                    LlamaBaseUrl = root.ContainsKey("llama_base_url")
                        ? Convert.ToString(root["llama_base_url"]) ?? ""
                        : ""
                };
            }
            catch (InvalidOperationException) { throw; }
            catch { throw new InvalidOperationException("MODEL_SELECTION_INVALID"); }
        }

        static NamedTunnelSettings LoadNamedTunnelSettings()
        {
            try
            {
                if (!File.Exists(NamedTunnelPath)) return null;
                var serializer = new JavaScriptSerializer();
                var root = serializer.DeserializeObject(
                    File.ReadAllText(NamedTunnelPath, Encoding.UTF8)) as Dictionary<string, object>;
                if (root == null) return null;
                var settings = new NamedTunnelSettings {
                    Name = root.ContainsKey("named_tunnel_name")
                        ? Convert.ToString(root["named_tunnel_name"]) ?? "" : "",
                    Hostname = root.ContainsKey("named_tunnel_hostname")
                        ? Convert.ToString(root["named_tunnel_hostname"]) ?? "" : "",
                    ConfigPath = root.ContainsKey("named_tunnel_config_path")
                        ? Convert.ToString(root["named_tunnel_config_path"]) ?? "" : ""
                };
                if (!Regex.IsMatch(settings.Name, @"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$") ||
                    !Regex.IsMatch(settings.Hostname, @"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])$") ||
                    settings.Hostname.EndsWith(".trycloudflare.com", StringComparison.OrdinalIgnoreCase) ||
                    !File.Exists(settings.ConfigPath))
                {
                    return null;
                }
                return settings;
            }
            catch
            {
                return null;
            }
        }

        static string NamedTunnelPowerShellArguments(NamedTunnelSettings settings)
        {
            if (settings == null)
                throw new InvalidOperationException(
                    "Production Named Tunnel is not configured. Use the one-time Named Tunnel setup first.");
            return " -TunnelMode Named" +
                " -NamedTunnelName " + PowerShellLiteral(settings.Name) +
                " -NamedTunnelHostname " + PowerShellLiteral(settings.Hostname) +
                " -NamedTunnelConfig " + PowerShellLiteral(settings.ConfigPath);
        }

        static void SaveSelection(
            string model,
            string baseUrl,
            IEnumerable<string> availableModels,
            string source,
            string thinkingEffort = null)
        {
            if (LoadRuntimeBinding() != null) throw new InvalidOperationException("EXPLICIT_BINDING_USE_OFFLINE_STRATA_SAVE_OR_REMOVE_INTENT");
            if (!SafeModelId(model))
                throw new InvalidOperationException("Invalid model ID / 模型 ID 格式不正確。");
            if (!SafeLoopbackBase(baseUrl))
                throw new InvalidOperationException("Invalid loopback llama.cpp URL / 本機 llama.cpp 網址不正確。");

            Directory.CreateDirectory(ConfigRoot);
            var serializer = new JavaScriptSerializer();
            var value = new Dictionary<string, object> {
                { "schema_version", 1 },
                { "product_version", Version },
                { "model", model },
                { "llama_base_url", baseUrl.TrimEnd('/') },
                { "available_models", availableModels == null ? new string[0] : availableModels.ToArray() },
                { "selected_utc", DateTime.UtcNow.ToString("o") },
                { "source", source },
                { "preferred_model", PreferredModel }
            };

            var profile = LoadModelProfile();
            if (thinkingEffort != null && profile == null) throw new InvalidOperationException("MODEL_PROFILE_REQUIRED");
            if (profile != null) {
                profile["model"] = model;
                if (thinkingEffort != null) {
                    profile["enable_thinking"] = thinkingEffort != "none";
                    profile["reasoning_effort"] = thinkingEffort;
                }
                string profileJson = serializer.Serialize(profile);
                ParseModelProfile(profileJson);
                value["model_profile_sha256"] = ModelProfileHash(profile);
                value["model_profile_qualified"] = false;
                string profileTemp = ModelProfilePath + ".tmp";
                File.WriteAllText(profileTemp, profileJson, new UTF8Encoding(false));
                if (File.Exists(ModelProfilePath)) File.Replace(profileTemp, ModelProfilePath, null);
                else File.Move(profileTemp, ModelProfilePath);
                Environment.SetEnvironmentVariable("V213_MODEL_PROFILE_JSON", profileJson);
            }
            string temporary = SelectionPath + ".tmp";
            File.WriteAllText(temporary, serializer.Serialize(value), new UTF8Encoding(false));
            if (File.Exists(SelectionPath))
                File.Replace(temporary, SelectionPath, null);
            else
                File.Move(temporary, SelectionPath);
        }

        static async Task<int> RunPowerShellAsync(
            string script,
            string arguments,
            bool showErrorDialog)
        {
            var selectedIntent = LoadSelection();
            if (selectedIntent.BindingJson != null) {
                string action = script.Replace('\\', '/');
                if (!(new [] { "run-v213-local-llm-bridge.ps1", "run-v213-local-llm-bridge-source-diverse.ps1",
                               "scripts/run_v213_local_llm_bridge_core.ps1", "scripts/run_v213_local_llm_bridge_core_v2.ps1" }).Contains(action))
                    throw new InvalidOperationException("EXPLICIT_BINDING_CALLER_UNSUPPORTED_USE_SEPARATE_BRIDGE_START");
                // Validate intent before even launcher log/wrapper directories.
                if (RunBindingHelper("--resolve-stdin", new Dictionary<string, object> { {"root", Root},
                    {"binding_json", selectedIntent.BindingJson} }, false) != 0) throw new InvalidOperationException("BINDING_PREFLIGHT_UNAVAILABLE");
            }
            string path = Path.IsPathRooted(script) ? script : Path.Combine(Root, script);
            if (!File.Exists(path))
            {
                LastPowerShellSummary = "Missing script / 找不到腳本:\r\n" + path;
                if (showErrorDialog)
                {
                    MessageBox.Show(
                        LastPowerShellSummary,
                        "Investor Intelligence",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                }
                return 2;
            }

            string logRoot = ProfileTestConfigRoot != null ? Path.Combine(ProfileTestConfigRoot, "logs") : Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "InvestorIntelligence", "logs", "launcher");
            Directory.CreateDirectory(logRoot);
            string stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + "-" +
                Path.GetFileNameWithoutExtension(path);
            string logPath = Path.Combine(logRoot, stamp + ".log");
            string rawPath = Path.Combine(logRoot, stamp + ".raw.log");
            string wrapperRoot = Path.Combine(
                Path.GetTempPath(),
                "ii-v213-capture-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(wrapperRoot);
            string psWrapper = Path.Combine(wrapperRoot, "invoke.ps1");
            string cmdWrapper = Path.Combine(wrapperRoot, "invoke.cmd");

            string psBody =
                "$ErrorActionPreference='Continue'\r\n" +
                "$utf8=New-Object System.Text.UTF8Encoding($false)\r\n" +
                "[Console]::OutputEncoding=$utf8\r\n" +
                "$OutputEncoding=$utf8\r\n" +
                "& " + PowerShellLiteral(path) + " " + arguments + "\r\n" +
                "if($null -ne $LASTEXITCODE){exit [int]$LASTEXITCODE}\r\n" +
                "if($?){exit 0}else{exit 1}\r\n";
            File.WriteAllText(psWrapper, psBody, new UTF8Encoding(true));

            string cmdBody =
                "@echo off\r\n" +
                "chcp 65001 >nul\r\n" +
                "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " +
                CmdQuoted(psWrapper) + " > " + CmdQuoted(rawPath) + " 2>&1\r\n" +
                "exit /b %ERRORLEVEL%\r\n";
            File.WriteAllText(cmdWrapper, cmdBody, Encoding.ASCII);

            LastPowerShellLiveLine =
                "II_PROGRESS launcher log created / 啟動器即時記錄已建立";
            int exitCode = -1;

            using (var stream = new FileStream(
                logPath,
                FileMode.Create,
                FileAccess.Write,
                FileShare.ReadWrite))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(true)))
            {
                writer.AutoFlush = true;
                writer.WriteLine("Investor Intelligence v" + Version + " " +
                    Revision + " live launcher log");
                writer.WriteLine("SCRIPT=" + path);
                writer.WriteLine("STARTED_LOCAL=" + DateTimeOffset.Now.ToString("o"));
                writer.WriteLine("LOG_MODE=LIVE_CHILD_FILE_TAIL");
                writer.WriteLine("PARENT_EXIT_IS_AUTHORITATIVE=TRUE");
                writer.WriteLine("ANONYMOUS_STDOUT_PIPES=FALSE");
                writer.WriteLine("RAW_OUTPUT_LOG=" + rawPath);
                writer.WriteLine("--- LIVE OUTPUT ---");

                var state = new CaptureState(writer);
                var startInfo = new ProcessStartInfo {
                    FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
                    Arguments = "/d /s /c \"\"" + cmdWrapper + "\"\"",
                    WorkingDirectory = Root,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                var profile = LoadModelProfile();
                if (profile != null) startInfo.EnvironmentVariables["V213_MODEL_PROFILE_JSON"] = new JavaScriptSerializer().Serialize(profile);
                var binding = LoadRuntimeBinding();
                if (binding != null) startInfo.EnvironmentVariables["V213_RUNTIME_BINDING_JSON"] = new JavaScriptSerializer().Serialize(binding);
                var process = new Process { StartInfo = startInfo };
                if (!process.Start())
                {
                    process.Dispose();
                    LastPowerShellSummary =
                        "PowerShell process could not be started.\r\nLog / 記錄：" + logPath;
                    writer.WriteLine("PROCESS_START_FAILED");
                    if (showErrorDialog)
                    {
                        MessageBox.Show(
                            LastPowerShellSummary,
                            "Investor Intelligence",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Error);
                    }
                    return 3;
                }

                writer.WriteLine("PROCESS_ID=" + process.Id);
                StreamReader rawReader = null;
                try
                {
                    while (!process.HasExited)
                    {
                        if (rawReader == null && File.Exists(rawPath))
                        {
                            try
                            {
                                rawReader = new StreamReader(
                                    new FileStream(
                                        rawPath,
                                        FileMode.Open,
                                        FileAccess.Read,
                                        FileShare.ReadWrite | FileShare.Delete),
                                    new UTF8Encoding(false, false),
                                    true);
                            }
                            catch (IOException) { }
                        }
                        if (rawReader != null)
                            DrainAvailableLines(rawReader, state);
                        await Task.Delay(200);
                    }

                    process.WaitForExit();
                    exitCode = process.ExitCode;
                    lock (state.Sync)
                    {
                        writer.WriteLine("PARENT_PROCESS_EXITED=TRUE");
                        writer.WriteLine("PARENT_EXIT_CODE=" + exitCode);
                        writer.Flush();
                    }

                    long previousLength = -1;
                    int stableChecks = 0;
                    for (int attempt = 0; attempt < 20; attempt++)
                    {
                        if (rawReader == null && File.Exists(rawPath))
                        {
                            rawReader = new StreamReader(
                                new FileStream(
                                    rawPath,
                                    FileMode.Open,
                                    FileAccess.Read,
                                    FileShare.ReadWrite | FileShare.Delete),
                                new UTF8Encoding(false, false),
                                true);
                        }
                        if (rawReader != null)
                            DrainAvailableLines(rawReader, state);

                        long length = File.Exists(rawPath)
                            ? new FileInfo(rawPath).Length
                            : 0;
                        if (length == previousLength) stableChecks++;
                        else stableChecks = 0;
                        previousLength = length;
                        if (stableChecks >= 3) break;
                        await Task.Delay(100);
                    }
                }
                finally
                {
                    if (rawReader != null) rawReader.Dispose();
                    process.Dispose();
                }

                lock (state.Sync)
                {
                    state.Open = false;
                    writer.WriteLine("RAW_OUTPUT_FINAL_DRAIN=COMPLETE");
                    writer.WriteLine("--- END OUTPUT ---");
                    writer.WriteLine("EXIT_CODE=" + exitCode);
                    writer.WriteLine("FINISHED_LOCAL=" + DateTimeOffset.Now.ToString("o"));
                    writer.Flush();
                }

                if (exitCode == 0)
                {
                    LastPowerShellSummary = "PASS\r\nLog / 記錄：" + logPath;
                    LastPowerShellLiveLine = "INVESTOR_INTELLIGENCE operation PASS";
                }
                else
                {
                    string detail;
                    lock (state.Sync)
                    {
                        detail = Tail(state.Tail.ToString().Trim(), 7000);
                    }
                    LastPowerShellSummary =
                        "Exit code / 結束碼: " + exitCode + "\r\n\r\n" +
                        (String.IsNullOrWhiteSpace(detail)
                            ? "No diagnostic output was returned."
                            : detail) +
                        "\r\n\r\nLog / 完整記錄：\r\n" + logPath +
                        "\r\nRaw output / 原始輸出：\r\n" + rawPath;
                    LastPowerShellLiveLine =
                        "V213_OPERATION_FAILED; see live log / 請查看即時記錄";
                    if (showErrorDialog)
                    {
                        MessageBox.Show(
                            LastPowerShellSummary,
                            "Investor Intelligence - Error / 錯誤",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Error);
                    }
                }
            }

            try { Directory.Delete(wrapperRoot, true); } catch { }
            return exitCode;
        }

        static Task<int> CheckLocalModelAsync(ModelSelection selection, bool showErrors)
        {
            if (selection.BindingJson != null) return Task.Run(() => {
                // Actual GUI -> direct core caller, without the generic logging,
                // bootstrap, wrapper-file or mutation sequence. Core returns at
                // its bounded selected-only metadata branch before all acts.
                string command = "& " + PowerShellLiteral(Path.Combine(Root, "scripts", "run_v213_local_llm_bridge_core.ps1")) +
                    " -BindingMetadataCheckOnly -ProjectRoot " + PowerShellLiteral(Root) +
                    " -BindingJson " + PowerShellLiteral(selection.BindingJson) +
                    " -Model " + PowerShellLiteral(selection.Model) + " -LlamaBaseUrl " + PowerShellLiteral(selection.LlamaBaseUrl) +
                    "; if (-not $?) { exit 1 }";
                var start = new ProcessStartInfo { FileName="powershell.exe", UseShellExecute=false, CreateNoWindow=true,
                    Arguments="-NoProfile -NonInteractive -EncodedCommand " + Convert.ToBase64String(Encoding.Unicode.GetBytes(command)),
                    RedirectStandardOutput=true, RedirectStandardError=true };
                using (var process = Process.Start(start)) {
                    var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
                    if (!process.WaitForExit(35000)) { process.Kill(); return 1; }
                    if (!stdout.Wait(1000) || !stderr.Wait(1000) || stdout.Result.Length > 16384 || stderr.Result.Length > 4096) return 1;
                    return process.ExitCode;
                }
            });
            return RunPowerShellAsync("scripts/run_v213_local_llm_bridge_core.ps1",
                (selection.BindingJson == null ? "-RoutingCheckOnly" : "-BindingMetadataCheckOnly") + " -ProjectRoot " + PowerShellLiteral(Root) +
                " -LlamaBaseUrl " + PowerShellLiteral(selection.LlamaBaseUrl) +
                " -Model " + PowerShellLiteral(selection.Model) +
                (selection.BindingJson == null ? "" : " -BindingJson " + PowerShellLiteral(selection.BindingJson)), showErrors);
        }

        static int RunPowerShellCli(string script, string arguments)
        {
            return RunPowerShellAsync(script, arguments, false)
                .GetAwaiter()
                .GetResult();
        }

        static int PipeHoldSelfTest()
        {
            string testRoot = Path.Combine(
                Path.GetTempPath(),
                "ii-v213-pipe-hold-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(testRoot);
            string script = Path.Combine(testRoot, "parent.ps1");
            string powershell = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe");
            string body =
                "$ErrorActionPreference='Stop'\r\n" +
                "Start-Process -FilePath " + PowerShellLiteral(powershell) +
                " -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 30')" +
                " -NoNewWindow | Out-Null\r\n" +
                "Write-Output 'II_PROGRESS PIPE_HOLD_PARENT_EXIT_TEST=PASS'\r\n" +
                "exit 0\r\n";
            File.WriteAllText(script, body, new UTF8Encoding(true));

            var stopwatch = Stopwatch.StartNew();
            int code = RunPowerShellAsync(script, "", false).GetAwaiter().GetResult();
            stopwatch.Stop();
            try { Directory.Delete(testRoot, true); } catch { }
            if (code != 0) return 41;
            if (stopwatch.Elapsed > TimeSpan.FromSeconds(12)) return 42;
            return 0;
        }

        static int ModelSelectionSelfTest()
        {
            const string PreferredModel = "synthetic-model-a";
            if (ModelProfileSelfTest() != 0) return 58;
            string json =
                "{\"data\":[{\"id\":\"gemma4\"},{\"id\":\"" +
                PreferredModel + "\"}]}";
            List<string> models = ExtractModelIds(json);
            if (models.Count != 2) return 51;
            var aliases = ExtractModelIds("{\"data\":[{\"id\":\"canonical-test\",\"aliases\":[\"" + PreferredModel + "\"]}]}");
            if (!aliases.Contains(PreferredModel)) return 56;
            try {
                ExtractModelIds("{\"data\":[{\"id\":\"canonical-test\",\"aliases\":[\"" + PreferredModel + "\"]},{\"id\":\"wrong\",\"aliases\":[\"" + PreferredModel + "\"]}]}");
                return 57;
            } catch (InvalidOperationException) { }
            if (!models.Any(id => id.Equals(
                    PreferredModel,
                    StringComparison.Ordinal))) return 52;
            if (!SafeModelId(PreferredModel)) return 53;
            if (!SafeLoopbackBase("http://127.0.0.1:8080")) return 54;
            foreach (string invalid in new[] { "http://localhost:8080?key=fixture", "http://localhost:8080#fixture", "http://fixture@localhost:8080", "http://localhost:8080/path", "https://example.com" })
                if (SafeLoopbackBase(invalid) || DiscoverModels(new ModelSelection { LlamaBaseUrl = invalid }).Error != "MODEL_ROUTER_URL_INVALID") return 66;
            var candidates = ModelBaseCandidates("http://localhost:9999/");
            if (candidates[0] != "http://localhost:9999" || candidates[1] != DefaultLlamaBase ||
                candidates.Any(b => new Uri(b).Port == 8000) || candidates.Distinct(StringComparer.OrdinalIgnoreCase).Count() != candidates.Count ||
                !candidates.Contains("http://127.0.0.1:11434") || ModelBaseCandidates("https://example.com")[0] != DefaultLlamaBase) return 68;
            if (ModelFamily("Qwen3.8-27B-EXL3-5.5bpw-v2") != "qwen3.8-27b" || ModelFamily("Qwen3.8-27B") != "qwen3.8-27b" ||
                ModelFamily("gemma4") != "gemma4") return 69;
            var moved = ChooseModel(new List<string> { "Qwen3.8-27B" }, new[] { "Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548", "Qwen3.8-27B-EXL3-5.5bpw-v2" });
            if (moved == null || moved[0] != "Qwen3.8-27B" || moved[1] != "family") return 73;
            var exact = ChooseModel(new List<string> { "other", "Qwen3.8-27B-EXL3-5.5bpw-v2" }, new[] { "", "qwen3.8-27b-exl3-5.5bpw-v2" });
            if (exact == null || exact[1] != "exact" || ChooseModel(new List<string> { "a-7B", "b-8B" }, new[] { "c-9B" }) != null) return 74;
            if (ModelBaseCandidates("", true).Any(b => new Uri(b).Port == 8000)) return 75;
            string many = "{\"data\":[" + String.Join(",", Enumerable.Range(0, 1025).Select(i => "{\"id\":\"synthetic-" + i + "\"}")) + "]}";
            try { ExtractModelIds(many); return 67; } catch (InvalidOperationException) { }
            return 0;
        }

        [STAThread]
        static int Main(string[] args)
        {
            if (args.Length == 1 && args[0] == "--version")
            {
                Console.WriteLine(
                    "Investor Intelligence " + Version + " " + Revision);
                return 0;
            }
            if (args.Contains("--credential-store-self-test"))
            {
                if (args.Length != 1) return 1;
                System.Type storeType = System.Type.GetType("InvestorIntelligence.SecureCredentialManager");
                if (storeType == null) return 3;
                System.Reflection.MethodInfo storeMethod = storeType.GetMethod("RunSelfTest", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static, null, System.Type.EmptyTypes, null);
                if (storeMethod == null) return 3;
                object storeResult = storeMethod.Invoke(null, null);
                return storeResult is int ? (int)storeResult : 3;
            }
            // Read-only native transport check: no selection, model start or preset mutation.
            if (args.Length > 0 && args[0] == "--model-catalog-check") {
                if (args.Length != 2 || !SafeLoopbackBase(args[1])) return 70;
                try {
                    var catalog = DiscoverModels(new ModelSelection { LlamaBaseUrl = args[1] });
                    return catalog.Models.Count > 0 ? 0 : 71;
                } catch { return 72; }
            }
            // Read-only auto-detection report (no selection or profile change): address, model and how it matched.
            if (args.Length == 1 && args[0] == "--model-discovery-check") {
                try {
                    var found = DiscoverModels(LoadSelection(), true);
                    Console.WriteLine(new JavaScriptSerializer().Serialize(new Dictionary<string, object> {
                        { "base_url", found.BaseUrl }, { "model", found.Chosen }, { "match", found.Match },
                        { "auto_detected", found.AutoDetected }, { "models", found.Models.Take(16).ToArray() }, { "error", found.Error } }));
                    return String.IsNullOrEmpty(found.Chosen) ? 71 : 0;
                } catch { return 72; }
            }
            if (args.Length == 1 && args[0] == "--binding-metadata-check") {
                try { var selected = LoadSelection(); return selected.BindingJson == null ? 71 : CheckLocalModelAsync(selected, false).GetAwaiter().GetResult(); }
                catch { return 72; }
            }
            if (args.Length > 0 && args[0] == "--model-route-check") {
                if (args.Length != 2) return 70;
                try {
                    var selected = LoadSelection();
                    if (selected.BindingJson != null) {
                        if (CanonicalStrataRoot(args[1], true) != selected.LlamaBaseUrl) return 70;
                        return RunBindingHelper("--routing-check-stdin", new Dictionary<string, object> { {"root", Root},
                            {"binding_json", selected.BindingJson}, {"base_url", selected.LlamaBaseUrl}, {"model", selected.Model} }, false);
                    }
                    if (!SafeLoopbackBase(args[1])) return 70;
                    var profile = LoadModelProfile();
                    if (profile == null) return 71;
                    return CheckLocalModelAsync(new ModelSelection {
                        Model = (string)profile["model"], LlamaBaseUrl = args[1]
                    }, false).GetAwaiter().GetResult();
                } catch { return 72; }
            }
            if (args.Contains("--pipe-hold-self-test"))
                return PipeHoldSelfTest();
            if (args.Contains("--model-profile-self-test")) return ModelProfileSelfTest();
            if (args.Contains("--model-thinking-ui-self-test")) return ModelProfileSelfTest(true);
            if (args.Contains("--model-selection-self-test"))
                return ModelSelectionSelfTest();
            if (args.Contains("--self-test"))
            {
                string[] required = {
                    "run-v213-local.ps1",
                    "run-v213-local-llm-bridge.ps1",
                    "activate-v213-seven-field-schedule.ps1",
                    "sync-v213-top20-report.ps1",
                    "install-v213-runtime.ps1",
                    "register-v213-refresh-tasks.ps1",
                    @"scripts\build_v213_scheduled_top20_report.py",
                    @"scripts\bootstrap_portable_python.ps1",
                    @"scripts\setup_v213_named_tunnel.ps1",
                    @"scripts\v213_named_tunnel_helpers.ps1",
                    @"scripts\v213_free_relay.ps1",
                    @"scripts\v213_free_relay_heartbeat.ps1",
                    "register-v213-free-relay-task.ps1",
                    "requirements-ci.txt",
                    @"scripts\run_v213_local_llm_bridge_core.ps1",
                    @"scripts\run_v213_local_llm_bridge_core_v2.ps1",
                    @"scripts\v213_windows_security.ps1",
                    @"scripts\v213_local_llm_gateway.py",
                    @"scripts\v213_model_profile.py",
                    @"scripts\v213_compact_qa_gateway.py",
                    @"config\v213-compact-qa-v1.json",
                    @"config\v213-model-profile-v1.json"
                };
                foreach (string item in required)
                {
                    if (!File.Exists(Path.Combine(Root, item)))
                    {
                        Console.Error.WriteLine("SELF_TEST_MISSING=" + item);
                        return 1;
                    }
                }
                Console.WriteLine(
                    "INVESTOR_INTELLIGENCE_V213_LAUNCHER_SELF_TEST=PASS");
                return 0;
            }
            if (args.Contains("--local"))
            {
                // Data-only: the hourly sealed publisher is the single Production writer.
                return RunPowerShellCli(
                    "run-v213-local.ps1",
                    "-ProjectRoot " + PowerShellLiteral(Root) +
                    " -InstallCloudflared -NoSync");
            }
            if (args.Contains("--activate-schedule"))
            {
                int refresh = RunPowerShellCli(
                    "run-v213-local.ps1",
                    "-ProjectRoot " + PowerShellLiteral(Root) +
                    " -InstallCloudflared -NoAutoActivation -TunnelMode FreeRelay");
                if (refresh != 0) return refresh;
                return RunPowerShellCli(
                    "activate-v213-seven-field-schedule.ps1",
                    "-ProjectRoot " + PowerShellLiteral(Root) +
                    " -ConfirmActivation -RequireLocalModel");
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
            return 0;
        }

        sealed class NamedTunnelDialog : Form
        {
            readonly TextBox nameBox;
            readonly TextBox hostnameBox;
            readonly TextBox configBox;
            public string TunnelName { get { return nameBox.Text.Trim(); } }
            public string TunnelHostname { get { return hostnameBox.Text.Trim(); } }
            public string TunnelConfig { get { return configBox.Text.Trim(); } }

            public NamedTunnelDialog(NamedTunnelSettings previous)
            {
                Text = "Production Named Tunnel setup / 命名通道設定";
                Width = 650;
                Height = 330;
                StartPosition = FormStartPosition.CenterParent;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;
                MinimizeBox = false;

                Controls.Add(new Label { Left = 20, Top = 18, Width = 590, Height = 36,
                    Text = "One-time Cloudflare Named Tunnel verification + DNS route setup.\nCredentials are validated but never printed or copied." });
                Controls.Add(new Label { Left = 20, Top = 65, Width = 180, Text = "NamedTunnelName" });
                nameBox = new TextBox { Left = 20, Top = 87, Width = 590,
                    Text = previous == null ? "" : previous.Name };
                Controls.Add(nameBox);
                Controls.Add(new Label { Left = 20, Top = 120, Width = 180, Text = "NamedTunnelHostname" });
                hostnameBox = new TextBox { Left = 20, Top = 142, Width = 590,
                    Text = previous == null ? "" : previous.Hostname };
                Controls.Add(hostnameBox);
                Controls.Add(new Label { Left = 20, Top = 175, Width = 180, Text = "NamedTunnelConfig" });
                configBox = new TextBox { Left = 20, Top = 197, Width = 490,
                    Text = previous == null ? "" : previous.ConfigPath };
                Controls.Add(configBox);
                var browse = new Button { Left = 520, Top = 195, Width = 90, Height = 27, Text = "Browse..." };
                browse.Click += delegate {
                    using (var picker = new OpenFileDialog())
                    {
                        picker.Filter = "YAML config (*.yml;*.yaml)|*.yml;*.yaml|All files (*.*)|*.*";
                        picker.CheckFileExists = true;
                        if (picker.ShowDialog(this) == DialogResult.OK) configBox.Text = picker.FileName;
                    }
                };
                Controls.Add(browse);
                var ok = new Button { Left = 410, Top = 240, Width = 95, Height = 30,
                    Text = "Verify / 驗證", DialogResult = DialogResult.OK };
                var cancel = new Button { Left = 515, Top = 240, Width = 95, Height = 30,
                    Text = "Cancel", DialogResult = DialogResult.Cancel };
                Controls.Add(ok);
                Controls.Add(cancel);
                AcceptButton = ok;
                CancelButton = cancel;
            }
        }

        // M1: offline candidate registration (nothing is probed, started or replaced).
        sealed class RegisterDialog : Form
        {
            readonly TextBox endpoint, model;
            readonly NumericUpDown priority, output, smoke, timeout;
            readonly ComboBox effort;
            public Dictionary<string, object> Entry;

            public RegisterDialog()
            {
                Text = "Register candidate (offline) / 登記候選（離線）";
                ClientSize = new Size(520, 330);
                StartPosition = FormStartPosition.CenterParent;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false; MinimizeBox = false;
                endpoint = new TextBox { Left = 190, Top = 12, Width = 310, Text = "http://127.0.0.1:8080" };
                model = new TextBox { Left = 190, Top = 44, Width = 310 };
                priority = new NumericUpDown { Left = 190, Top = 76, Width = 120, Minimum = 1, Maximum = 64, Value = 1 };
                effort = new ComboBox { Left = 190, Top = 108, Width = 160, DropDownStyle = ComboBoxStyle.DropDownList };
                effort.Items.AddRange(new object[] { "none", "minimal", "low", "medium", "high", "xhigh", "max" });
                effort.SelectedItem = "none";
                output = new NumericUpDown { Left = 190, Top = 140, Width = 120, Minimum = 1, Maximum = 8192, Value = 1024 };
                smoke = new NumericUpDown { Left = 190, Top = 172, Width = 120, Minimum = 1, Maximum = 8192, Value = 128 };
                timeout = new NumericUpDown { Left = 190, Top = 204, Width = 120, Minimum = 1000, Maximum = 20000, Value = 18000 };
                string[] labels = { "Strata loopback endpoint", "Exact model ID", "Priority (1 = preferred)", "THINK / reasoning effort", "Max output tokens", "Smoke output tokens", "Timeout ms" };
                for (int i = 0; i < labels.Length; i++) Controls.Add(new Label { Left = 12, Top = 15 + 32 * i, Width = 172, Height = 24, Text = labels[i] });
                Controls.AddRange(new Control[] { endpoint, model, priority, effort, output, smoke, timeout });
                Controls.Add(new Label { Left = 12, Top = 240, Width = 496, Height = 34, Text = "Enrollment is offline: no request is sent. Ports 5000 and 8000 are refused. The profile fields are request settings, NOT qualification." });
                var ok = new Button { Left = 300, Top = 288, Width = 100, Height = 28, Text = "OK" };
                var cancel = new Button { Left = 408, Top = 288, Width = 100, Height = 28, Text = "Cancel", DialogResult = DialogResult.Cancel };
                ok.Click += delegate {
                    try { Entry = Build(); DialogResult = DialogResult.OK; }
                    catch { MessageBox.Show("Invalid candidate fields; nothing registered."); }
                };
                Controls.Add(ok); Controls.Add(cancel);
                AcceptButton = ok; CancelButton = cancel;
            }

            Dictionary<string, object> Build()
            {
                string root = CanonicalStrataRoot(endpoint.Text.Trim(), true);
                string id = model.Text;
                string level = effort.SelectedItem as string;
                if (!SafeModelId(id) || level == null) throw new InvalidOperationException("CATALOG_ENTRY_INVALID");
                var profile = new Dictionary<string, object> {
                    { "schema_version", 1 }, { "model", id }, { "enable_thinking", level != "none" }, { "reasoning_effort", level },
                    { "max_output_tokens", (int)output.Value }, { "smoke_output_tokens", (int)smoke.Value }, { "timeout_ms", (int)timeout.Value } };
                return new Dictionary<string, object> { { "base_url", root }, { "model", id }, { "profile", profile }, { "priority", (int)priority.Value } };
            }
        }

        // M1: real registry UI. Each row keeps endpoint + exact model + binding digest and its actual status. REGISTERED is enrollment only;
        // SERVED_METADATA_ONLY is a user-triggered /health + /v1/models check of that exact model (not qualification); SELECTED_INTENT is
        // saved request intent (NOT a weight replacement); resident-weight replacement is REPLACEMENT_BLOCKED.
        sealed class ModelRegistryForm : Form
        {
            readonly ListView list;
            readonly Label info;
            readonly CheckBox optIn;
            readonly Button registerButton, removeButton, refreshButton, selectButton, autoButton, closeButton;
            bool working, loading;

            public ModelRegistryForm()
            {
                Text = "Model registry / 本機模型登記（僅請求意圖，未資格化）";
                ClientSize = new Size(960, 470);
                StartPosition = FormStartPosition.CenterParent;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false; MinimizeBox = false;
                list = new ListView { Left = 12, Top = 12, Width = 936, Height = 290, View = View.Details, FullRowSelect = true, MultiSelect = false, HideSelection = false };
                list.Columns.Add("Priority", 60); list.Columns.Add("Endpoint", 150); list.Columns.Add("Model", 230);
                list.Columns.Add("Binding digest", 110); list.Columns.Add("Status", 150); list.Columns.Add("Reason / context", 225);
                optIn = new CheckBox { Left = 12, Top = 308, Width = 936, Height = 40,
                    Text = "Priority SUGGESTION (opt-in, read-only): on a button press or once at EXE start, propose the SERVED_METADATA_ONLY registered candidate with the lowest priority number. It never saves, activates or replaces anything and never runs on a timer; you must confirm with Select verified." };
                registerButton = new Button { Left = 12, Top = 356, Width = 150, Height = 28, Text = "Register… / 登記" };
                removeButton = new Button { Left = 172, Top = 356, Width = 120, Height = 28, Text = "Remove / 移除" };
                refreshButton = new Button { Left = 302, Top = 356, Width = 160, Height = 28, Text = "Refresh metadata / 重新整理" };
                selectButton = new Button { Left = 472, Top = 356, Width = 170, Height = 28, Text = "Select verified / 選用" };
                autoButton = new Button { Left = 652, Top = 356, Width = 170, Height = 28, Text = "Suggest by priority / 依優先序建議" };
                closeButton = new Button { Left = 832, Top = 356, Width = 116, Height = 28, Text = "Close / 關閉", DialogResult = DialogResult.Cancel };
                info = new Label { Left = 12, Top = 396, Width = 936, Height = 64,
                    Text = "REGISTERED = enrolled offline only. Lower priority number = preferred by the read-only priority suggestion (confirmation required). Replacing the resident model weights is REPLACEMENT_BLOCKED (BLOCKED_EXCLUSIVITY_AND_NATIVE_ADMISSION): selecting only saves request intent." };
                Controls.AddRange(new Control[] { list, optIn, registerButton, removeButton, refreshButton, selectButton, autoButton, closeButton, info });
                CancelButton = closeButton;
                registerButton.Click += async delegate { await RegisterAsync(); };
                removeButton.Click += async delegate { await RemoveAsync(); };
                refreshButton.Click += async delegate { await RefreshAsync(); };
                selectButton.Click += async delegate { await SelectAsync(); };
                autoButton.Click += async delegate { await SuggestAsync(); };
                optIn.CheckedChanged += async delegate { await OptInChangedAsync(); };
                Shown += async delegate { await ReloadAsync(); };
            }

            static string FiniteReason(Exception error)
            {
                string text = error is InvalidOperationException ? error.Message : "";
                return Regex.IsMatch(text ?? "", @"\A[A-Z][A-Z0-9_]{0,63}\z") ? text : "CATALOG_OPERATION_UNAVAILABLE";
            }

            string SelectedDigest()
            {
                return list.SelectedItems.Count == 1 ? list.SelectedItems[0].Tag as string : null;
            }

            void SetWorking(bool value)
            {
                working = value;
                foreach (Control control in new Control[] { list, optIn, registerButton, removeButton, refreshButton, selectButton, autoButton })
                    control.Enabled = !value;
                UseWaitCursor = value;
            }

            async Task<bool> RunAsync(string label, Func<Dictionary<string, object>> work, Action<Dictionary<string, object>> done)
            {
                if (working) return false;
                SetWorking(true);
                info.Text = label;
                try
                {
                    Dictionary<string, object> result = await Task.Run(work);
                    done(result);
                    return true;
                }
                catch (Exception error)
                {
                    info.Text = "Not applied / 未套用: " + FiniteReason(error) + "\r\nNothing was started, stopped, loaded or replaced.";
                    return false;
                }
                finally { SetWorking(false); }
            }

            void ApplyCommon(Dictionary<string, object> result)
            {
                loading = true;
                try { optIn.Checked = result.ContainsKey("auto_select_opt_in") && result["auto_select_opt_in"] is bool && (bool)result["auto_select_opt_in"]; }
                finally { loading = false; }
            }

            void Fill(System.Collections.IEnumerable rows)
            {
                list.Items.Clear();
                if (rows == null) return;
                foreach (object raw in rows)
                {
                    var row = raw as Dictionary<string, object>;
                    if (row == null) continue;
                    string digest = Convert.ToString(row["binding_sha256"]);
                    string state = row.ContainsKey("state") ? Convert.ToString(row["state"]) : "REGISTERED";
                    string detail = "";
                    if (row.ContainsKey("reason") && !String.IsNullOrEmpty(Convert.ToString(row["reason"]))) detail = Convert.ToString(row["reason"]);
                    else if (row.ContainsKey("declared_context") && row["declared_context"] != null)
                        detail = "context " + Convert.ToString(row["declared_context"]) + " / METADATA_ONLY, UNQUALIFIED";
                    var item = new ListViewItem(new[] { Convert.ToString(row["priority"]), Convert.ToString(row["base_url"]), Convert.ToString(row["model"]),
                        digest.Length >= 12 ? digest.Substring(0, 12) : digest, state, detail });
                    item.Tag = digest;
                    list.Items.Add(item);
                }
            }

            void MarkSelected(string digest)
            {
                foreach (ListViewItem item in list.Items)
                    if ((item.Tag as string) == digest) item.SubItems[4].Text = "SELECTED_INTENT";
            }

            async Task ReloadAsync()
            {
                await RunAsync("Reading the registry (offline) / 讀取登記",
                    delegate { return RunCatalogHelper("list", new Dictionary<string, object>(), true); },
                    delegate(Dictionary<string, object> r) {
                        ApplyCommon(r); Fill(r["candidates"] as System.Collections.IEnumerable);
                        info.Text = "REGISTERED = enrolled offline only; no network was used. Press Refresh to read metadata from the registered endpoints.";
                    });
            }

            async Task RegisterAsync()
            {
                Dictionary<string, object> entry;
                using (var dialog = new RegisterDialog())
                {
                    if (dialog.ShowDialog(this) != DialogResult.OK) return;
                    entry = dialog.Entry;
                }
                await RunAsync("Registering offline / 離線登記",
                    delegate { return RunCatalogHelper("register", new Dictionary<string, object> { { "entry", entry } }, true); },
                    delegate(Dictionary<string, object> r) {
                        ApplyCommon(r); Fill(r["candidates"] as System.Collections.IEnumerable);
                        info.Text = "REGISTERED (offline). It is not advertised as served until a metadata refresh proves it.";
                    });
            }

            async Task RemoveAsync()
            {
                string digest = SelectedDigest();
                if (digest == null) { info.Text = "Select one row first / 請先選一列"; return; }
                if (MessageBox.Show("Remove this registry entry (offline)? Nothing is stopped or unloaded.", "Model registry", MessageBoxButtons.YesNo) != DialogResult.Yes) return;
                await RunAsync("Removing offline / 離線移除",
                    delegate { return RunCatalogHelper("remove", new Dictionary<string, object> { { "binding_sha256", digest } }, true); },
                    delegate(Dictionary<string, object> r) {
                        ApplyCommon(r); Fill(r["candidates"] as System.Collections.IEnumerable);
                        info.Text = "Removed from the registry (offline).";
                    });
            }

            async Task RefreshAsync()
            {
                await RunAsync("Reading metadata from the registered endpoints only (20 s total, /health and /v1/models) / 讀取已登記端點",
                    delegate { return RunCatalogHelper("refresh", new Dictionary<string, object> { { "root", Root } }, true); },
                    delegate(Dictionary<string, object> r) {
                        ApplyCommon(r); Fill(r["rows"] as System.Collections.IEnumerable);
                        info.Text = "METADATA_ONLY / UNQUALIFIED. SERVED_METADATA_ONLY means /health and /v1/models answered for the exact registered model: not qualification, not capacity. The result is not stored; selection re-verifies.";
                    });
            }

            async Task SelectAsync()
            {
                string digest = SelectedDigest();
                if (digest == null) { info.Text = "Select one row first / 請先選一列"; return; }
                await RunAsync("Verifying the exact candidate, then saving request intent / 驗證後儲存請求意圖",
                    delegate { return RunCatalogSelection("select", new Dictionary<string, object> { { "root", Root }, { "binding_sha256", digest } }); },
                    delegate(Dictionary<string, object> r) {
                        MarkSelected(digest);
                        info.Text = "SELECTED_INTENT / UNQUALIFIED: request intent saved for that exact endpoint, model and profile. This is NOT a weight replacement (REPLACEMENT_BLOCKED); nothing was started, stopped or loaded.";
                    });
            }

            // READ-ONLY: refreshes the registered endpoints and highlights the lowest-priority served candidate as a PROPOSAL. Nothing is
            // saved; the user confirms with Select verified, which is the only path that writes request intent.
            async Task SuggestAsync()
            {
                await RunAsync("Refreshing the registered endpoints, then computing a READ-ONLY priority suggestion / 讀取並計算建議",
                    delegate { return RunCatalogHelper("suggest", new Dictionary<string, object> { { "root", Root }, { "startup", false } }, true); },
                    delegate(Dictionary<string, object> r) {
                        Fill(r["rows"] as System.Collections.IEnumerable);
                        string state = r.ContainsKey("state") ? Convert.ToString(r["state"]) : "";
                        string digest = r.ContainsKey("binding_sha256") ? Convert.ToString(r["binding_sha256"]) : "";
                        foreach (ListViewItem item in list.Items)
                        {
                            if ((item.Tag as string) != digest || (state != "PROPOSED" && state != "ALREADY_SELECTED")) continue;
                            item.SubItems[5].Text = state == "PROPOSED" ? "PROPOSED by priority: confirm with Select verified" : "ALREADY the saved intent";
                            item.Selected = true; item.EnsureVisible();
                        }
                        info.Text = (state == "PROPOSED" ? "AUTO_SELECTION_PROPOSAL (suggestion only): the highlighted row has the lowest priority among served candidates. "
                            : state == "ALREADY_SELECTED" ? "The suggested candidate is already the saved intent. " : "No proposal: " + state + ". ") +
                            "Nothing was saved or activated; confirm with Select verified. UNQUALIFIED; replacement stays blocked.";
                    });
            }

            async Task OptInChangedAsync()
            {
                if (loading || working) return;
                bool desired = optIn.Checked;
                bool ok = await RunAsync("Saving the auto-select opt-in (offline) / 儲存設定",
                    delegate { return RunCatalogHelper("set-opt-in", new Dictionary<string, object> { { "value", desired } }, true); },
                    delegate(Dictionary<string, object> r) {
                        ApplyCommon(r);
                        info.Text = desired ? "Priority-suggestion opt-in saved (offline). It only proposes, on an explicit press or once at EXE start; nothing is saved or activated without your confirmation." : "Priority-suggestion opt-in cleared (offline).";
                    });
                if (!ok) await ReloadAsync();
            }
        }

        sealed class MainForm : Form
        {
            readonly Label headerLabel;
            readonly Label status;
            readonly Label endpointLabel;
            readonly ComboBox modelBox;
            readonly ComboBox thinkingBox;
            readonly ComboBox bindingMode;
            readonly TextBox bindingEndpoint;
            readonly NumericUpDown bindingOutput, bindingSmoke, bindingTimeout;
            readonly bool thinkingAvailable;
            readonly Button scanButton;
            readonly Button checkModelButton;
            readonly Button useModelButton;
            readonly Button refreshButton;
            readonly Button activateButton;
            readonly Button bridgeButton;
            readonly Button folderButton;
            readonly Button namedTunnelButton;
            readonly Button freeRelayButton;
            readonly Timer elapsedTimer;
            readonly List<string> discoveredModels = new List<string>();

            DateTime operationStartedUtc;
            string operationLabel = "";
            string discoveredBaseUrl = "";
            bool busy;

            public MainForm(bool discoverOnShow = true)
            {
                Text = "Investor Intelligence v" + Version + " " + Revision;
                Width = 720;
                Height = 650;
                StartPosition = FormStartPosition.CenterScreen;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;

                headerLabel = new Label {
                    Left = 24,
                    Top = 18,
                    Width = 650,
                    Height = 48,
                    Text = "Investor Intelligence v2.1.3 " + Revision +
                        "\n本地模型 + 七欄 LINE / Local Model + Seven-Field LINE",
                    Font = new Font(
                        "Segoe UI",
                        13F,
                        FontStyle.Bold)
                };
                Controls.Add(headerLabel);
                var headerMeasured = TextRenderer.MeasureText(
                    headerLabel.Text,
                    headerLabel.Font,
                    new Size(headerLabel.Width, 32767),
                    TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl);
                int headerDelta = Math.Max(0, headerMeasured.Height - headerLabel.Height);
                headerLabel.Height += headerDelta;

                Controls.Add(new Label {
                    Left = 24,
                    Top = 76,
                    Width = 190,
                    Height = 22,
                    Text = "本地模型 / Local model"
                });

                modelBox = new ComboBox {
                    Left = 24,
                    Top = 99,
                    Width = 430,
                    Height = 28,
                    DropDownStyle = ComboBoxStyle.DropDown
                };
                ModelSelection saved = LoadSelection();
                modelBox.Text = SafeModelId(saved.Model)
                    ? saved.Model
                    : PreferredModel;
                discoveredBaseUrl = SafeLoopbackBase(saved.LlamaBaseUrl)
                    ? saved.LlamaBaseUrl.TrimEnd('/')
                    : DefaultLlamaBase;
                Controls.Add(modelBox);

                scanButton = new Button {
                    Left = 466,
                    Top = 97,
                    Width = 100,
                    Height = 31,
                    Text = "掃描 / Scan"
                };
                useModelButton = new Button {
                    Left = 576,
                    Top = 97,
                    Width = 100,
                    Height = 31,
                    Text = "使用 / Use"
                };
                Controls.Add(scanButton);
                Controls.Add(useModelButton);

                endpointLabel = new Label {
                    Left = 24,
                    Top = 132,
                    Width = 650,
                    Height = 22,
                    Text = "llama.cpp: " + discoveredBaseUrl +
                        "  |  Selected: " + modelBox.Text
                };
                Controls.Add(endpointLabel);

                refreshButton = MakeButton(
                    "啟動所選模型並更新資料\nStart selected model + refresh",
                    24,
                    166);
                activateButton = MakeButton(
                    "正式啟用 08:00 / 21:00 七欄推送\n" +
                    "Activate scheduled seven-field LINE",
                    360,
                    166);
                bridgeButton = MakeButton(
                    "只啟動所選模型橋接\nStart selected-model bridge only",
                    24,
                    266);
                folderButton = MakeButton(
                    "開啟程式資料夾\nOpen package folder",
                    360,
                    266);
                freeRelayButton = new Button {
                    Left = 24,
                    Top = 360,
                    Width = 316,
                    Height = 62,
                    Text = "免費 Relay 自動重連\nEnable FREE_RELAY reconnect",
                    UseVisualStyleBackColor = true
                };
                namedTunnelButton = new Button {
                    Left = 360,
                    Top = 360,
                    Width = 316,
                    Height = 62,
                    Text = "選用 Named Tunnel\nOptional future stable path",
                    UseVisualStyleBackColor = true
                };
                Controls.Add(refreshButton);
                Controls.Add(activateButton);
                Controls.Add(bridgeButton);
                Controls.Add(folderButton);
                Controls.Add(freeRelayButton);
                Controls.Add(namedTunnelButton);

                status = new Label {
                    Left = 24,
                    Top = 445,
                    Width = 652,
                    Height = 105,
                    Text = "設定待驗證 / Configuration not qualified\r\nPreferred / 預設首選: " +
                        PreferredModel,
                    BorderStyle = BorderStyle.FixedSingle,
                    Padding = new Padding(8)
                };
                Controls.Add(status);

                elapsedTimer = new Timer { Interval = 1000 };
                elapsedTimer.Tick += delegate {
                    if (!busy) return;
                    TimeSpan elapsed = DateTime.UtcNow - operationStartedUtc;
                    string progress = LastPowerShellLiveLine;
                    if (String.IsNullOrWhiteSpace(progress))
                    {
                        progress =
                            "請保持視窗開啟；即時 log 正在寫入 / Keep this window open";
                    }
                    status.Text = operationLabel + "  " +
                        elapsed.ToString(@"mm\:ss") + "\r\n" + progress;
                };

                scanButton.Click += async delegate { await RefreshModelsAsync(); };
                useModelButton.Click += delegate {
                    ModelSelection selection;
                    if (!TryCommitSelection(out selection)) return;
                    status.Text =
                        "模型選擇已儲存，尚未通過回答／think 驗證 / Saved, not qualified\r\n" +
                        selection.Model + " @ " + selection.LlamaBaseUrl +
                        "\r\nTHINK: " + (string)thinkingBox.SelectedItem;
                };

                freeRelayButton.Click += async delegate {
                    var answer = MessageBox.Show(
                        "啟用登入時 FREE_RELAY 自動重連？此模式使用免費、非固定的 TryCloudflare URL，workers.dev 仍是固定入口。\n\nEnable automatic FREE_RELAY reconnect at logon?",
                        "Enable FREE_RELAY reconnect",
                        MessageBoxButtons.YesNo,
                        MessageBoxIcon.Question);
                    if (answer != DialogResult.Yes) return;
                    await RunBusyAsync(
                        "設定 FREE_RELAY 自動重連 / Enabling reconnect...",
                        async delegate {
                            return await RunPowerShellAsync(
                                "register-v213-free-relay-task.ps1",
                                "-ProjectRoot " + PowerShellLiteral(Root) + " -Enable",
                                true);
                        },
                        "FREE_RELAY 自動重連已啟用 / Reconnect enabled",
                        "FREE_RELAY 自動重連設定失敗 / Setup failed");
                };

                namedTunnelButton.Click += async delegate {
                    NamedTunnelSettings previous = LoadNamedTunnelSettings();
                    using (var dialog = new NamedTunnelDialog(previous))
                    {
                        if (dialog.ShowDialog(this) != DialogResult.OK) return;
                        string name = dialog.TunnelName;
                        string hostname = dialog.TunnelHostname;
                        string config = dialog.TunnelConfig;
                        await RunBusyAsync(
                            "Named Tunnel 驗證與 DNS 路由設定中 / Verifying Named Tunnel...",
                            async delegate {
                                return await RunPowerShellAsync(
                                    @"scripts\setup_v213_named_tunnel.ps1",
                                    "-ProjectRoot " + PowerShellLiteral(Root) +
                                    " -NamedTunnelName " + PowerShellLiteral(name) +
                                    " -NamedTunnelHostname " + PowerShellLiteral(hostname) +
                                    " -NamedTunnelConfig " + PowerShellLiteral(config),
                                    true);
                            },
                            "Named Tunnel 設定完成 / Named Tunnel ready\r\n" + hostname,
                            "Named Tunnel 設定失敗；未變更 bridge / Setup failed");
                    }
                };

                refreshButton.Click += async delegate {
                    ModelSelection selection;
                    if (!TryCommitSelection(out selection)) return;
                    string model = selection.Model;
                    string baseUrl = selection.LlamaBaseUrl;
                    await RunBusyAsync(
                        "更新中 / Refreshing...",
                        async delegate {
                            // Data-only: the hourly sealed publisher is the single Production writer.
                            return await RunPowerShellAsync(
                                "run-v213-local.ps1",
                                "-ProjectRoot " + PowerShellLiteral(Root) +
                                " -InstallCloudflared -NoSync -Model " + PowerShellLiteral(model) +
                                " -LlamaBaseUrl " + PowerShellLiteral(baseUrl),
                                true);
                        },
                        "更新完成 / Refresh completed\r\nModel: " + model,
                        "更新失敗；已顯示詳細原因 / Refresh failed");
                };

                activateButton.Click += async delegate {
                    ModelSelection selection;
                    if (!TryCommitSelection(out selection)) return;
                    string model = selection.Model;
                    string baseUrl = selection.LlamaBaseUrl;
                    var answer = MessageBox.Show(
                        "選定模型：\n" + model +
                        "\n\n將先重新刷新並驗證同一模型；只有 exact-model health gate" +
                        " 通過才部署。\n\nSelected model:\n" + model +
                        "\n\nA fresh exact-model preflight runs before deployment. Continue?",
                        "Confirm v2.1.3 activation",
                        MessageBoxButtons.YesNo,
                        MessageBoxIcon.Warning);
                    if (answer != DialogResult.Yes) return;

                    await RunBusyAsync(
                        "啟用前刷新 / Preflight refresh...",
                        async delegate {
                            int refresh = await RunPowerShellAsync(
                                "run-v213-local.ps1",
                                "-ProjectRoot " + PowerShellLiteral(Root) +
                                " -InstallCloudflared -NoAutoActivation" +
                                " -Model " + PowerShellLiteral(model) +
                                " -LlamaBaseUrl " + PowerShellLiteral(baseUrl) +
                                " -TunnelMode FreeRelay",
                                true);
                            if (refresh != 0) return refresh;

                            operationLabel = "正式啟用中 / Activating...";
                            LastPowerShellLiveLine =
                                "II_PROGRESS exact selected-model preflight complete /" +
                                " 所選模型驗證完成";
                            return await RunPowerShellAsync(
                                "activate-v213-seven-field-schedule.ps1",
                                "-ProjectRoot " + PowerShellLiteral(Root) +
                                " -ConfirmActivation -RequireLocalModel" +
                                " -ExpectedModel " + PowerShellLiteral(model),
                                true);
                        },
                        "正式啟用完成 / Activation completed\r\nModel: " + model,
                        "啟用失敗；Production 保留/rollback 狀態請看詳細訊息 /" +
                        " Activation failed");
                };

                bridgeButton.Click += async delegate {
                    ModelSelection selection;
                    if (!TryCommitSelection(out selection)) return;
                    string model = selection.Model;
                    string baseUrl = selection.LlamaBaseUrl;
                    await RunBusyAsync(
                        "免費 workers.dev Relay 橋接啟動中 / Starting FREE_RELAY...",
                        async delegate {
                            return await RunPowerShellAsync(
                                "run-v213-local-llm-bridge.ps1",
                                "-ProjectRoot " + PowerShellLiteral(Root) +
                                " -InstallCloudflared -StopExisting" +
                                " -Model " + PowerShellLiteral(model) +
                                " -LlamaBaseUrl " + PowerShellLiteral(baseUrl) +
                                (selection.BindingJson == null ? "" : " -BindingJson " + PowerShellLiteral(selection.BindingJson)) +
                                " -TunnelMode FreeRelay",
                                true);
                        },
                        "本地模型橋接完成 / Model bridge ready\r\nModel: " + model,
                        "模型橋接失敗；已顯示詳細原因 / Bridge failed");
                };

                folderButton.Click += delegate {
                    Process.Start("explorer.exe", "\"" + Root + "\"");
                };

                FormClosing += delegate(object sender, FormClosingEventArgs e) {
                    if (!busy) return;
                    e.Cancel = true;
                    MessageBox.Show(
                        "目前仍在執行刷新／啟用程序，請等程序結束後再關閉。" +
                        "\n\nAn operation is still running.",
                        "Investor Intelligence - Running / 執行中",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Information);
                };

                // Explicit request intent is visible/editable, never a discovery
                // result. Offline Use and metadata Check do not start a service.
                // Add the mode controls without compressing existing action/status text.
                foreach (Control control in Controls) if (control.Top >= 166) control.Top += 64;
                Height += 64;
                var initialProfile = LoadModelProfile();
                thinkingAvailable = initialProfile != null;
                thinkingBox = new ComboBox {
                    Left = 166, Top = 162, Width = 160, Height = 28,
                    DropDownStyle = ComboBoxStyle.DropDownList,
                    AccessibleName = "THINK reasoning effort", Enabled = thinkingAvailable
                };
                thinkingBox.Items.AddRange(new object[] { "none", "minimal", "low", "medium", "high", "xhigh", "max" });
                thinkingBox.SelectedItem = initialProfile == null ? "none" : (string)initialProfile["reasoning_effort"];
                Controls.Add(new Label { Left = 24, Top = 165, Width = 140, Height = 24, Text = "THINK / 推理上限" });
                Controls.Add(thinkingBox);
                Controls.Add(new Label { Left = 340, Top = 160, Width = 335, Height = 48,
                    Text = "none = 關閉；其他 = 上限，每題依反應時間\n自動調整 / Auto below cap" });
                thinkingBox.SelectedIndexChanged += delegate {
                    status.Text = "THINK 設定尚未儲存／驗證 / Pending, unqualified";
                };
                checkModelButton = new Button { Left = 166, Top = 195, Width = 160, Height = 28,
                    Text = "本機回覆測試 / Test reply" };
                Controls.Add(checkModelButton);
                checkModelButton.Click += async delegate {
                    ModelSelection selection;
                    if (!TryCommitSelection(out selection)) return;
                    await RunBusyAsync(selection.BindingJson == null ? "驗證本機固定回覆 / Checking local reply..." : "Selected metadata only / UNQUALIFIED", async delegate {
                        return await CheckLocalModelAsync(selection, true);
                    }, selection.BindingJson == null ? "本機固定回覆通過；未資格化 / Marker passed, not qualified" : "METADATA_ONLY / UNQUALIFIED；不是完整回答或容量證明",
                       "本機回覆測試失敗 / Local reply check failed");
                };

                foreach (Control control in Controls) if (control.Top >= 160) control.Top += 120;
                Height += 120;
                bindingMode = new ComboBox { Left=24, Top=160, Width=320, Height=26, DropDownStyle=ComboBoxStyle.DropDownList };
                bindingMode.Items.AddRange(new object[] { "Legacy discovery", "Strata REQUEST INTENT / UNQUALIFIED" });
                bindingMode.SelectedIndex = saved.BindingJson == null ? 0 : 1;
                bindingEndpoint = new TextBox { Left=24, Top=190, Width=650, Text=discoveredBaseUrl, AccessibleName="Exact Strata loopback endpoint" };
                bindingOutput = new NumericUpDown { Left=24, Top=224, Width=120, Minimum=1, Maximum=8192, Value=initialProfile == null ? 1024 : (int)initialProfile["max_output_tokens"] };
                bindingSmoke = new NumericUpDown { Left=166, Top=224, Width=120, Minimum=1, Maximum=8192, Value=initialProfile == null ? 128 : (int)initialProfile["smoke_output_tokens"] };
                bindingTimeout = new NumericUpDown { Left=308, Top=224, Width=120, Minimum=1000, Maximum=20000, Value=initialProfile == null ? 18000 : (int)initialProfile["timeout_ms"] };
                Controls.AddRange(new Control[] {bindingMode,bindingEndpoint,bindingOutput,bindingSmoke,bindingTimeout,
                    new Label {Left=24,Top=251,Width=650,Text="Output / Smoke tokens / Timeout ms — request settings, NOT qualification"}});
                bindingMode.SelectedIndexChanged += delegate { scanButton.Enabled = !busy && bindingMode.SelectedIndex == 0; checkModelButton.Text = bindingMode.SelectedIndex == 1 ? "Metadata / 未資格化" : "本機回覆測試 / Test reply"; status.Text="REQUEST INTENT — UNQUALIFIED; no model/LINE start"; };
                if (bindingMode.SelectedIndex == 1) { scanButton.Enabled=false; checkModelButton.Text="Metadata / 未資格化"; }
                var removeIntentButton = new Button { Left=364, Top=160, Width=310, Height=26, Text="Remove intent (offline) / 移除意圖" };
                removeIntentButton.Click += delegate {
                    if (busy || MessageBox.Show("Explicitly remove saved request intent? No model/LINE start.", "Remove intent", MessageBoxButtons.YesNo) != DialogResult.Yes) return;
                    try { RemoveExplicitBinding(); bindingMode.SelectedIndex=0; status.Text="OFFLINE_INTENT_REMOVED / UNQUALIFIED; no activation"; }
                    catch { MessageBox.Show("BINDING_REMOVE_UNAVAILABLE; clear external intent explicitly; no activation"); }
                };
                Controls.Add(removeIntentButton);

                // M1: real registry UI (register / remove / list / manual exact choice / opt-in priority selection). Make room for one row
                // exactly as the blocks above do. It saves REQUEST INTENT only; weights are never replaced.
                foreach (Control control in Controls) if (control.Top >= 280) control.Top += 36;
                Height += 36;
                var registryButton = new Button { Left = 24, Top = 282, Width = 320, Height = 26, UseVisualStyleBackColor = true,
                    Text = "Model registry… / 模型登記與選擇", AccessibleName = "Model registry" };
                registryButton.Click += delegate {
                    if (busy) return;
                    using (var dialog = new ModelRegistryForm()) dialog.ShowDialog(this);
                    try {
                        if (LoadRuntimeBinding() != null) {
                            ModelSelection chosen = LoadSelection();
                            bindingMode.SelectedIndex = 1;
                            bindingEndpoint.Text = chosen.LlamaBaseUrl; modelBox.Text = chosen.Model;
                            endpointLabel.Text = "REQUEST INTENT / UNQUALIFIED: " + chosen.Model + " @ " + chosen.LlamaBaseUrl;
                        }
                    } catch { status.Text = "BINDING_STATE_UNAVAILABLE after the registry; no activation"; }
                };
                Controls.Add(registryButton);

                if (headerDelta > 0)
                {
                    foreach (Control control in Controls)
                    {
                        if (control != headerLabel)
                        {
                            control.Top += headerDelta;
                        }
                    }
                    Height += headerDelta;
                }

                if (discoverOnShow) Shown += async delegate { await RefreshModelsAsync(); await StartupAutoSelectAsync(); };
            }

            public int ThinkingUiSelfTest(string isolated)
            {
                // Only synthetic choices and isolated profile storage. No discovery,
                // inference, activation, task registration or production buttons.
                foreach (var button in new[] { scanButton, checkModelButton, refreshButton, activateButton, bridgeButton,
                    folderButton, namedTunnelButton, freeRelayButton }) button.Enabled = false;
                Show();

                // Regression: validate measured header fits without clipping.
                var measuredHeader = TextRenderer.MeasureText(
                    headerLabel.Text,
                    headerLabel.Font,
                    new Size(headerLabel.Width, 32767),
                    TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl);
                if (headerLabel.Height < measuredHeader.Height) return 80;
                if (!headerLabel.Text.Contains(Revision)) return 81;

                // Validate header does not overlap subsequent controls.
                foreach (Control control in Controls)
                {
                    if (control != headerLabel && headerLabel.Bounds.IntersectsWith(control.Bounds))
                        return 82;
                }

                // Validate all controls fit ClientRectangle.
                foreach (Control control in Controls)
                {
                    if (!ClientRectangle.Contains(control.Bounds))
                        return 83;
                }

                // Validate no unexpected control intersections.
                for (int i = 0; i < Controls.Count; i++)
                {
                    for (int j = i + 1; j < Controls.Count; j++)
                    {
                        if (Controls[i].Bounds.IntersectsWith(Controls[j].Bounds))
                            return 84;
                    }
                }

                // Negative probe 1: too-short header must be rejected.
                int originalHeight = headerLabel.Height;
                try
                {
                    headerLabel.Height = Math.Max(0, measuredHeader.Height - 1);
                    var tooShortProbe = TextRenderer.MeasureText(
                        headerLabel.Text,
                        headerLabel.Font,
                        new Size(headerLabel.Width, 32767),
                        TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl);
                    if (headerLabel.Height >= tooShortProbe.Height) return 85;
                }
                finally
                {
                    headerLabel.Height = originalHeight;
                }

                // Negative probe 2: intentional header overlap must be detected.
                try
                {
                    headerLabel.Height = originalHeight + 50;
                    bool detectedOverlap = false;
                    foreach (Control control in Controls)
                    {
                        if (control != headerLabel && headerLabel.Bounds.IntersectsWith(control.Bounds))
                        {
                            detectedOverlap = true;
                            break;
                        }
                    }
                    if (!detectedOverlap) return 86;
                }
                finally
                {
                    headerLabel.Height = originalHeight;
                }

                // Verify restored geometry is completely valid.
                if (headerLabel.Height < measuredHeader.Height) return 87;
                foreach (Control control in Controls)
                {
                    if (control != headerLabel && headerLabel.Bounds.IntersectsWith(control.Bounds))
                        return 88;
                }

                if (!thinkingBox.Visible || !ClientRectangle.Contains(thinkingBox.Bounds) ||
                    thinkingBox.DropDownStyle != ComboBoxStyle.DropDownList) return 77;
                foreach (string model in new[] { "synthetic-ui-a", "synthetic-ui-b" }) {
                    discoveredModels.Clear(); discoveredModels.Add(model);
                    modelBox.Items.Clear(); modelBox.Items.Add(model); modelBox.Text = model;
                    foreach (string effort in new[] { "none", "minimal", "low", "medium", "high", "xhigh", "max", "none" }) {
                        thinkingBox.SelectedItem = effort;
                        useModelButton.PerformClick();
                        var persisted = ParseModelProfile(File.ReadAllText(ModelProfilePath, Encoding.UTF8));
                        if ((string)persisted["model"] != model || (string)persisted["reasoning_effort"] != effort ||
                            (bool)persisted["enable_thinking"] != (effort != "none")) return 73;
                        var saved = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(SelectionPath, Encoding.UTF8)) as Dictionary<string, object>;
                        if ((bool)saved["model_profile_qualified"] || (string)saved["model_profile_sha256"] != ModelProfileHash(persisted) ||
                            !status.Text.Contains("not qualified")) return 74;
                        if (effort == "none" || effort == "xhigh") {
                            string probe = Path.Combine(isolated, "thinking-ui-child.ps1");
                            File.WriteAllText(probe, "$p=$env:V213_MODEL_PROFILE_JSON|ConvertFrom-Json; if($p.model -cne " + PowerShellLiteral(model) +
                                " -or $p.reasoning_effort -cne " + PowerShellLiteral(effort) + " -or $p.enable_thinking -ne " +
                                (effort == "none" ? "$false" : "$true") + "){exit 1}; exit 0", new UTF8Encoding(false));
                            if (Task.Run(() => RunPowerShellCli(probe, "")).GetAwaiter().GetResult() != 0) return 75;
                        }
                    }
                }
                string validBytes = File.ReadAllText(ModelProfilePath, Encoding.UTF8);
                try {
                    SaveSelection("synthetic-ui-b", DefaultLlamaBase, discoveredModels, "synthetic-test", "invalid-mode");
                    return 78;
                } catch (InvalidOperationException) { }
                if (File.ReadAllText(ModelProfilePath, Encoding.UTF8) != validBytes) return 79;
                SetBusy(true, "synthetic busy check");
                bool locked = !thinkingBox.Enabled && !modelBox.Enabled && !useModelButton.Enabled;
                SetBusy(false, "");
                if (!locked || !thinkingBox.Enabled) return 76;
                Close();
                return 0;
            }

            // M1 opt-in startup SUGGESTION, at most once per start, only when a registry file exists and the user enabled it. It is READ-ONLY:
            // it never saves, activates or replaces anything; it only shows a proposal that the user must confirm in the registry dialog
            // with Select verified. The operation holds the busy state through finally so no dialog or manual action can race it.
            async Task StartupAutoSelectAsync()
            {
                if (busy || !File.Exists(Path.Combine(ConfigRoot, "v213-model-registry-v1.json"))) return;
                SetBusy(true, "Opt-in priority suggestion (read-only) / 讀取優先序建議");
                try
                {
                    var result = await Task.Run(() => RunCatalogHelper("suggest", new Dictionary<string, object> { { "root", Root }, { "startup", true } }, true));
                    string state = result.ContainsKey("state") ? Convert.ToString(result["state"]) : "";
                    if (state == "PROPOSED")
                        status.Text = "AUTO_SELECTION_PROPOSAL (suggestion only): " + Convert.ToString(result["model"]) + " @ " + Convert.ToString(result["base_url"]) +
                            " has the lowest priority among served candidates. Nothing was saved or activated: open Model registry and press Select verified to confirm.";
                }
                catch (Exception error)
                {
                    string text = error is InvalidOperationException ? error.Message : "";
                    status.Text = "Priority suggestion unavailable: " + (Regex.IsMatch(text ?? "", @"\A[A-Z][A-Z0-9_]{0,63}\z") ? text : "CATALOG_OPERATION_UNAVAILABLE");
                }
                finally { SetBusy(false, ""); }
            }

            async Task RefreshModelsAsync()
            {
                if (busy) return;
                if (bindingMode.SelectedIndex == 1 || LoadRuntimeBinding() != null) { status.Text="Explicit Strata cannot discover/substitute; save intent or run metadata check."; return; }
                SetBusy(true, "讀取所選 Router 清單 / Reading selected Router catalog...");
                try {
                string requested = modelBox.Text.Trim();
                ModelSelection previous = LoadSelection();
                ModelCatalog catalog = await Task.Run(
                    delegate { return DiscoverModels(previous, true); });
                discoveredModels.Clear();
                modelBox.Items.Clear();

                if (catalog.Models.Count > 0)
                {
                    discoveredBaseUrl = catalog.BaseUrl;
                    discoveredModels.AddRange(catalog.Models);
                    foreach (string id in catalog.Models)
                        modelBox.Items.Add(id);

                    string current = requested;
                    string canonical = catalog.Models.FirstOrDefault(
                        id => id.Equals(current, StringComparison.OrdinalIgnoreCase));
                    if (canonical == null)
                    {
                        canonical = catalog.Models.FirstOrDefault(
                            id => id.Equals(
                                PreferredModel,
                                StringComparison.OrdinalIgnoreCase));
                    }
                    bool modelChanged = false;
                    if (canonical == null && !String.IsNullOrEmpty(catalog.Chosen))
                    {
                        canonical = catalog.Chosen;  // the saved model is gone: same family or the only model served
                        modelChanged = true;
                    }
                    if (canonical != null)
                        modelBox.SelectedItem = canonical;

                    endpointLabel.Text =
                        "Local model server: " + discoveredBaseUrl +
                        "  |  Models: " + catalog.Models.Count +
                        "  |  Selected: " + modelBox.Text;
                    status.Text = (modelChanged
                        ? "已自動偵測到本機模型（模型已變更：" + requested + " → " + canonical + "）/ Auto-detected a changed model\r\n"
                        : catalog.AutoDetected
                        ? "已自動偵測到本機模型伺服器（位址已變更）/ Auto-detected a new local address\r\n"
                        : "模型掃描完成 / Model scan completed\r\n") +
                        "請確認後按「使用 / Use」。";
                }
                else
                {
                    endpointLabel.Text =
                        "Local model server: not detected / 未偵測  |  Typed model: " +
                        modelBox.Text;
                    status.Text =
                        "未讀到模型清單；啟動本機模型伺服器（ninfer、llama.cpp、Ollama、LM Studio）後再掃描。\r\n" +
                        catalog.Error;
                }

                } catch {
                    discoveredModels.Clear();
                    modelBox.Items.Clear();
                    status.Text = "模型清單不可用；未更換模型 / Catalog unavailable; selection unchanged.";
                } finally {
                    SetBusy(false, "");
                }
            }

            bool TryCommitSelection(out ModelSelection selection)
            {
                selection = null;
                string requestedModel = bindingMode.SelectedIndex == 1 ? modelBox.Text : modelBox.Text.Trim();
                if (bindingMode.SelectedIndex == 1) {
                    try {
                        if (!thinkingAvailable || thinkingBox.SelectedItem == null) throw new InvalidOperationException("MODEL_PROFILE_REQUIRED");
                        SaveExplicitBinding(requestedModel, bindingEndpoint.Text, (string)thinkingBox.SelectedItem,
                            (int)bindingOutput.Value, (int)bindingSmoke.Value, (int)bindingTimeout.Value);
                        selection=LoadSelection();
                        endpointLabel.Text="REQUEST INTENT / UNQUALIFIED: " + selection.Model + " @ " + selection.LlamaBaseUrl;
                        return true;
                    } catch { MessageBox.Show("EXPLICIT_BINDING_SAVE_UNAVAILABLE; no model/LINE actuation"); return false; }
                }
                string requestedBaseUrl = discoveredBaseUrl.TrimEnd('/');

                if (!SafeModelId(requestedModel))
                {
                    MessageBox.Show(
                        "請選擇有效模型 ID。\nChoose a valid model ID.",
                        "Investor Intelligence",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Warning);
                    return false;
                }
                if (!SafeLoopbackBase(requestedBaseUrl))
                    requestedBaseUrl = DefaultLlamaBase;

                if (discoveredModels.Count == 0) {
                    MessageBox.Show("請先取得所選 Router 的有效模型清單；不猜測模型。\nRead a valid Router catalog before changing models.", "Investor Intelligence", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return false;
                }
                if (discoveredModels.Count > 0)
                {
                    string lookupModel = requestedModel;
                    string canonical = discoveredModels.FirstOrDefault(
                        id => id.Equals(
                            lookupModel,
                            StringComparison.OrdinalIgnoreCase));
                    if (canonical == null)
                    {
                        MessageBox.Show(
                            "所選模型不在目前 router 清單中。請重新掃描。\n" +
                            "Selected model is not in the current router catalog.",
                            "Investor Intelligence",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Warning);
                        return false;
                    }
                    requestedModel = canonical;
                    modelBox.Text = canonical;
                }

                if (thinkingAvailable && thinkingBox.SelectedItem == null) {
                    MessageBox.Show("請選擇 THINK 模式 / Select a reasoning mode.");
                    return false;
                }
                try
                {
                    SaveSelection(
                        requestedModel,
                        requestedBaseUrl,
                        discoveredModels,
                        "launcher_model_selector",
                        thinkingAvailable ? (string)thinkingBox.SelectedItem : null);
                    selection = new ModelSelection {
                        Model = requestedModel,
                        LlamaBaseUrl = requestedBaseUrl
                    };
                    endpointLabel.Text =
                        "llama.cpp: " + requestedBaseUrl +
                        "  |  Selected: " + requestedModel;
                    return true;
                }
                catch (Exception ex)
                {
                    MessageBox.Show(
                        ex.Message,
                        "Investor Intelligence",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                    return false;
                }
            }

            async Task RunBusyAsync(
                string label,
                Func<Task<int>> operation,
                string successText,
                string failureText)
            {
                if (busy) return;
                SetBusy(true, label);
                int code = -1;
                try
                {
                    code = await operation();
                    status.Text = code == 0 ? successText : failureText;
                }
                catch (Exception ex)
                {
                    status.Text = failureText;
                    MessageBox.Show(
                        "Unexpected launcher error / 啟動器非預期錯誤:\r\n\r\n" +
                        ex.Message,
                        "Investor Intelligence - Error / 錯誤",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                }
                finally
                {
                    SetBusy(false, "");
                    if (code == 0) status.Text = successText;
                }
            }

            void SetBusy(bool value, string label)
            {
                busy = value;
                scanButton.Enabled = !value && bindingMode.SelectedIndex == 0;
                bindingMode.Enabled = !value; bindingEndpoint.Enabled = !value; bindingOutput.Enabled = !value; bindingSmoke.Enabled = !value; bindingTimeout.Enabled = !value;
                checkModelButton.Enabled = !value;
                useModelButton.Enabled = !value;
                modelBox.Enabled = !value;
                thinkingBox.Enabled = !value && thinkingAvailable;
                refreshButton.Enabled = !value;
                activateButton.Enabled = !value;
                bridgeButton.Enabled = !value;
                folderButton.Enabled = !value;
                namedTunnelButton.Enabled = !value;
                freeRelayButton.Enabled = !value;
                UseWaitCursor = value;

                if (value)
                {
                    LastPowerShellLiveLine =
                        "II_PROGRESS preparing operation / 準備執行";
                    operationStartedUtc = DateTime.UtcNow;
                    operationLabel = label;
                    status.Text = label + "\r\n" + LastPowerShellLiveLine;
                    elapsedTimer.Start();
                }
                else
                {
                    elapsedTimer.Stop();
                    operationLabel = "";
                    UseWaitCursor = false;
                }
            }

            Button MakeButton(string text, int left, int top)
            {
                return new Button {
                    Left = left,
                    Top = top,
                    Width = 316,
                    Height = 82,
                    Text = text,
                    UseVisualStyleBackColor = true
                };
            }
        }
    }
}
