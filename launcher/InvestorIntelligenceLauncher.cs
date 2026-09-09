using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
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

        static int ModelProfileSelfTest() {
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
                raw = File.ReadAllText(path, Encoding.UTF8);
            }
            try { return ParseModelProfile(raw); }
            catch { throw new InvalidOperationException("MODEL_PROFILE_INVALID"); }
        }

        static readonly string[] KnownLlamaBases = {
            "http://127.0.0.1:8080",
            "http://127.0.0.1:7905",
            "http://127.0.0.1:14410",
            "http://127.0.0.1:8813",
            "http://127.0.0.1:8081",
            "http://127.0.0.1:8000"
        };

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
        }

        sealed class ModelCatalog
        {
            public string BaseUrl = "";
            public readonly List<string> Models = new List<string>();
            public string Error = "";
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
            return uri.Port >= 1 && uri.Port <= 65535 &&
                (uri.AbsolutePath == "/" || uri.AbsolutePath == "");
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
                    if (!result.Any(existing => existing.Equals(name, StringComparison.OrdinalIgnoreCase))) result.Add(name);
                }
            }
            return result;
        }

        static string HttpGet(string url)
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Proxy = null;
            request.KeepAlive = false;
            request.Timeout = 4500;
            request.ReadWriteTimeout = 4500;
            request.Headers[HttpRequestHeader.CacheControl] = "no-cache";

            using (var response = (HttpWebResponse)request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8, true))
            {
                if ((int)response.StatusCode < 200 || (int)response.StatusCode >= 300)
                    throw new InvalidOperationException("HTTP " + (int)response.StatusCode);
                return reader.ReadToEnd();
            }
        }

        static ModelCatalog DiscoverModels(ModelSelection previous)
        {
            var catalog = new ModelCatalog();
            var bases = new List<string>();

            if (previous != null && SafeLoopbackBase(previous.LlamaBaseUrl))
                bases.Add(previous.LlamaBaseUrl.TrimEnd('/'));
            foreach (string item in KnownLlamaBases)
            {
                if (!bases.Any(existing => existing.Equals(item, StringComparison.OrdinalIgnoreCase)))
                    bases.Add(item);
            }

            string last = "";
            foreach (string baseUrl in bases)
            {
                foreach (string suffix in new[] { "/models", "/v1/models" })
                {
                    try
                    {
                        List<string> ids = ExtractModelIds(HttpGet(baseUrl + suffix));
                        if (ids.Count == 0) continue;
                        catalog.BaseUrl = baseUrl;
                        catalog.Models.AddRange(ids.OrderBy(
                            id => id.Equals(PreferredModel, StringComparison.OrdinalIgnoreCase)
                                ? "0" + id
                                : "1" + id,
                            StringComparer.OrdinalIgnoreCase));
                        return catalog;
                    }
                    catch (Exception ex)
                    {
                        last = baseUrl + suffix + ": " + ex.Message;
                    }
                }
            }

            catalog.Error = String.IsNullOrWhiteSpace(last)
                ? "No llama.cpp model catalog was reachable."
                : last;
            return catalog;
        }

        static ModelSelection LoadSelection()
        {
            try
            {
                if (!File.Exists(SelectionPath)) return new ModelSelection();
                var serializer = new JavaScriptSerializer();
                var root = serializer.DeserializeObject(
                    File.ReadAllText(SelectionPath, Encoding.UTF8)) as Dictionary<string, object>;
                if (root == null) return new ModelSelection();

                return new ModelSelection {
                    Model = !String.IsNullOrEmpty(PreferredModel) ? PreferredModel : (root.ContainsKey("model") ? Convert.ToString(root["model"]) ?? "" : ""),
                    LlamaBaseUrl = root.ContainsKey("llama_base_url")
                        ? Convert.ToString(root["llama_base_url"]) ?? ""
                        : ""
                };
            }
            catch
            {
                return new ModelSelection();
            }
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
            string source)
        {
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
            if (profile != null) {
                profile["model"] = model;
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

            string logRoot = Path.Combine(
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
            return 0;
        }

        [STAThread]
        static int Main(string[] args)
        {
            if (args.Contains("--version"))
            {
                Console.WriteLine(
                    "Investor Intelligence " + Version + " " + Revision);
                return 0;
            }
            if (args.Contains("--pipe-hold-self-test"))
                return PipeHoldSelfTest();
            if (args.Contains("--model-profile-self-test")) return ModelProfileSelfTest();
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
                    "requirements-ci.txt"
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
                return RunPowerShellCli(
                    "run-v213-local.ps1",
                    "-ProjectRoot " + PowerShellLiteral(Root) +
                    " -InstallCloudflared");
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

        sealed class MainForm : Form
        {
            readonly Label status;
            readonly Label endpointLabel;
            readonly ComboBox modelBox;
            readonly Button scanButton;
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

            public MainForm()
            {
                Text = "Investor Intelligence v" + Version + " " + Revision;
                Width = 720;
                Height = 650;
                StartPosition = FormStartPosition.CenterScreen;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;

                Controls.Add(new Label {
                    Left = 24,
                    Top = 18,
                    Width = 650,
                    Height = 48,
                    Text = "Investor Intelligence v2.1.3 " + Revision +
                        "\n本地模型 + 七欄 LINE / Local Model + Seven-Field LINE",
                    Font = new System.Drawing.Font(
                        "Segoe UI",
                        13F,
                        System.Drawing.FontStyle.Bold)
                });

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
                    : "http://127.0.0.1:8080";
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
                    Text = "Ready / 就緒\r\nPreferred / 預設首選: " +
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
                        "模型選擇已儲存 / Model selection saved\r\n" +
                        selection.Model + " @ " + selection.LlamaBaseUrl;
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
                            return await RunPowerShellAsync(
                                "run-v213-local.ps1",
                                "-ProjectRoot " + PowerShellLiteral(Root) +
                                " -InstallCloudflared -Model " + PowerShellLiteral(model) +
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

                Shown += async delegate { await RefreshModelsAsync(); };
            }

            async Task RefreshModelsAsync()
            {
                if (busy) return;
                scanButton.Enabled = false;
                useModelButton.Enabled = false;
                status.Text =
                    "正在掃描 llama.cpp 模型 / Scanning llama.cpp models...";

                ModelSelection previous = LoadSelection();
                ModelCatalog catalog = await Task.Run(
                    delegate { return DiscoverModels(previous); });
                discoveredModels.Clear();
                modelBox.Items.Clear();

                if (catalog.Models.Count > 0)
                {
                    discoveredBaseUrl = catalog.BaseUrl;
                    discoveredModels.AddRange(catalog.Models);
                    foreach (string id in catalog.Models)
                        modelBox.Items.Add(id);

                    string current = modelBox.Text.Trim();
                    string canonical = catalog.Models.FirstOrDefault(
                        id => id.Equals(current, StringComparison.OrdinalIgnoreCase));
                    if (canonical == null)
                    {
                        canonical = catalog.Models.FirstOrDefault(
                            id => id.Equals(
                                PreferredModel,
                                StringComparison.OrdinalIgnoreCase));
                    }
                    if (canonical != null)
                        modelBox.SelectedItem = canonical;

                    endpointLabel.Text =
                        "llama.cpp: " + discoveredBaseUrl +
                        "  |  Models: " + catalog.Models.Count +
                        "  |  Selected: " + modelBox.Text;
                    status.Text =
                        "模型掃描完成 / Model scan completed\r\n" +
                        "請確認後按「使用 / Use」。";
                }
                else
                {
                    endpointLabel.Text =
                        "llama.cpp: not detected / 未偵測  |  Typed model: " +
                        modelBox.Text;
                    status.Text =
                        "未讀到模型清單；可啟動 llama.cpp 後再掃描。\r\n" +
                        catalog.Error;
                }

                scanButton.Enabled = true;
                useModelButton.Enabled = true;
            }

            bool TryCommitSelection(out ModelSelection selection)
            {
                selection = null;
                string requestedModel = modelBox.Text.Trim();
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
                    requestedBaseUrl = "http://127.0.0.1:8080";

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

                try
                {
                    SaveSelection(
                        requestedModel,
                        requestedBaseUrl,
                        discoveredModels,
                        "launcher_model_selector");
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
                scanButton.Enabled = !value;
                useModelButton.Enabled = !value;
                modelBox.Enabled = !value;
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
