using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace InvestorIntelligence
{
    static class Program
    {
        const string Version = "2.1.3";
        const string Revision = "FileCapture-R41";
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

        static string Root
        {
            get { return AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar); }
        }

        static string Tail(string text, int max)
        {
            if (String.IsNullOrEmpty(text)) return "";
            return text.Length <= max ? text : text.Substring(text.Length - max);
        }

        static string UiSafeProgressLine(string line)
        {
            if (String.IsNullOrWhiteSpace(line)) return "";
            string value = line.Trim().Replace("\r", " ").Replace("\n", " ");
            if (
                value.StartsWith("II_STAGE ", StringComparison.Ordinal) ||
                value.StartsWith("II_PROGRESS ", StringComparison.Ordinal) ||
                value.StartsWith("V213_", StringComparison.Ordinal) ||
                value.StartsWith("INVESTOR_INTELLIGENCE_", StringComparison.Ordinal)
            )
            {
                return value.Length <= 135 ? value : value.Substring(0, 132) + "...";
            }
            return "";
        }

        static void AppendTail(StringBuilder tail, string channel, string line)
        {
            tail.Append(channel).Append(" ").AppendLine(line);
            const int keep = 18000;
            if (tail.Length > keep + 4000)
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

        static async Task<int> RunPowerShellAsync(string script, string arguments, bool showErrorDialog)
        {
            string path = Path.IsPathRooted(script) ? script : Path.Combine(Root, script);
            if (!File.Exists(path))
            {
                LastPowerShellSummary = "Missing script / 找不到腳本:\r\n" + path;
                if (showErrorDialog)
                    MessageBox.Show(LastPowerShellSummary, "Investor Intelligence", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }

            string logRoot = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "InvestorIntelligence", "logs", "launcher");
            Directory.CreateDirectory(logRoot);
            string stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + "-" + Path.GetFileNameWithoutExtension(path);
            string logPath = Path.Combine(logRoot, stamp + ".log");
            string rawPath = Path.Combine(logRoot, stamp + ".raw.log");
            string wrapperRoot = Path.Combine(Path.GetTempPath(), "ii-v213-capture-" + Guid.NewGuid().ToString("N"));
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
                "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " + CmdQuoted(psWrapper) +
                " > " + CmdQuoted(rawPath) + " 2>&1\r\n" +
                "exit /b %ERRORLEVEL%\r\n";
            File.WriteAllText(cmdWrapper, cmdBody, Encoding.ASCII);

            LastPowerShellLiveLine = "II_PROGRESS launcher log created / 啟動器即時記錄已建立";
            int exitCode = -1;

            using (var stream = new FileStream(logPath, FileMode.Create, FileAccess.Write, FileShare.ReadWrite))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(true)))
            {
                writer.AutoFlush = true;
                writer.WriteLine("Investor Intelligence v" + Version + " " + Revision + " live launcher log");
                writer.WriteLine("SCRIPT=" + path);
                writer.WriteLine("STARTED_LOCAL=" + DateTimeOffset.Now.ToString("o"));
                writer.WriteLine("LOG_MODE=LIVE_CHILD_FILE_TAIL");
                writer.WriteLine("PARENT_EXIT_IS_AUTHORITATIVE=TRUE");
                writer.WriteLine("ANONYMOUS_STDOUT_PIPES=FALSE");
                writer.WriteLine("RAW_OUTPUT_LOG=" + rawPath);
                writer.WriteLine("--- LIVE OUTPUT ---");

                var state = new CaptureState(writer);
                var psi = new ProcessStartInfo
                {
                    FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
                    Arguments = "/d /s /c \"\"" + cmdWrapper + "\"\"",
                    WorkingDirectory = Root,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                var process = new Process();
                process.StartInfo = psi;
                if (!process.Start())
                {
                    process.Dispose();
                    LastPowerShellSummary = "PowerShell process could not be started.\r\nLog / 記錄：" + logPath;
                    writer.WriteLine("PROCESS_START_FAILED");
                    if (showErrorDialog)
                        MessageBox.Show(LastPowerShellSummary, "Investor Intelligence", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
                                    new FileStream(rawPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete),
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

                    // Drain any final parent-process writes without ever waiting for
                    // the raw file handle to close. Long-lived descendants may keep
                    // that ordinary file handle open, but cannot block the launcher.
                    long previousLength = -1;
                    int stableChecks = 0;
                    for (int attempt = 0; attempt < 20; attempt++)
                    {
                        if (rawReader == null && File.Exists(rawPath))
                        {
                            rawReader = new StreamReader(
                                new FileStream(rawPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete),
                                new UTF8Encoding(false, false),
                                true);
                        }
                        if (rawReader != null)
                            DrainAvailableLines(rawReader, state);
                        long length = File.Exists(rawPath) ? new FileInfo(rawPath).Length : 0;
                        if (length == previousLength) stableChecks++; else stableChecks = 0;
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
                    lock (state.Sync) { detail = Tail(state.Tail.ToString().Trim(), 6000); }
                    LastPowerShellSummary =
                        "Exit code / 結束碼: " + exitCode + "\r\n\r\n" +
                        (String.IsNullOrWhiteSpace(detail) ? "No diagnostic output was returned." : detail) +
                        "\r\n\r\nLog / 完整記錄：\r\n" + logPath +
                        "\r\nRaw output / 原始輸出：\r\n" + rawPath;
                    LastPowerShellLiveLine = "V213_OPERATION_FAILED; see live log / 請查看即時記錄";
                    if (showErrorDialog)
                        MessageBox.Show(LastPowerShellSummary, "Investor Intelligence - Error / 錯誤", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
            try { Directory.Delete(wrapperRoot, true); } catch { }
            return exitCode;
        }

        static int RunPowerShellCli(string script, string arguments)
        {
            return RunPowerShellAsync(script, arguments, false).GetAwaiter().GetResult();
        }

        static int PipeHoldSelfTest()
        {
            string testRoot = Path.Combine(Path.GetTempPath(), "ii-v213-pipe-hold-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(testRoot);
            string script = Path.Combine(testRoot, "parent.ps1");
            string pidFile = Path.Combine(testRoot, "child.pid");
            string powershell = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe");
            string body =
                "$ErrorActionPreference='Stop'\r\n" +
                "$child=Start-Process -FilePath " + PowerShellLiteral(powershell) +
                " -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 30') -NoNewWindow -PassThru\r\n" +
                "Set-Content -LiteralPath " + PowerShellLiteral(pidFile) + " -Value $child.Id -Encoding ascii\r\n" +
                "Write-Output 'II_PROGRESS PIPE_HOLD_PARENT_EXIT_TEST=PASS'\r\n" +
                "exit 0\r\n";
            File.WriteAllText(script, body, new UTF8Encoding(true));

            var stopwatch = Stopwatch.StartNew();
            int code = RunPowerShellAsync(script, "", false).GetAwaiter().GetResult();
            stopwatch.Stop();
            try
            {
                if (File.Exists(pidFile))
                {
                    int childPid;
                    if (Int32.TryParse(File.ReadAllText(pidFile).Trim(), out childPid))
                    {
                        try { Process.GetProcessById(childPid).Kill(); } catch { }
                    }
                }
            }
            catch { }
            try { Directory.Delete(testRoot, true); } catch { }

            if (code != 0) return 41;
            if (stopwatch.Elapsed > TimeSpan.FromSeconds(12)) return 42;
            return 0;
        }

        [STAThread]
        static int Main(string[] args)
        {
            if (args.Contains("--version"))
            {
                Console.WriteLine("Investor Intelligence " + Version + " " + Revision);
                return 0;
            }
            if (args.Contains("--pipe-hold-self-test"))
                return PipeHoldSelfTest();
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
                Console.WriteLine("INVESTOR_INTELLIGENCE_V213_LAUNCHER_SELF_TEST=PASS");
                return 0;
            }
            if (args.Contains("--local"))
                return RunPowerShellCli("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared");
            if (args.Contains("--activate-schedule"))
            {
                int refresh = RunPowerShellCli("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared -NoAutoActivation");
                if (refresh != 0) return refresh;
                return RunPowerShellCli("activate-v213-seven-field-schedule.ps1", "-ProjectRoot \"" + Root + "\" -ConfirmActivation -RequireLocalModel");
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
            return 0;
        }

        sealed class MainForm : Form
        {
            readonly Label status;
            readonly Button refreshButton;
            readonly Button activateButton;
            readonly Button modelButton;
            readonly Button folderButton;
            readonly Timer elapsedTimer;
            DateTime operationStartedUtc;
            string operationLabel = "";
            bool busy;

            public MainForm()
            {
                Text = "Investor Intelligence v" + Version + " " + Revision;
                Width = 640;
                Height = 410;
                StartPosition = FormStartPosition.CenterScreen;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;

                Controls.Add(new Label {
                    Left = 24, Top = 22, Width = 580, Height = 50,
                    Text = "Investor Intelligence v2.1.3 " + Revision + "\n本地模型 + 七欄 LINE / Local Model + Seven-Field LINE",
                    Font = new System.Drawing.Font("Segoe UI", 13F, System.Drawing.FontStyle.Bold)
                });

                refreshButton = MakeButton("啟動本地模型並更新資料\nStart local model + refresh", 24, 90);
                activateButton = MakeButton("正式啟用 08:00 / 21:00 七欄推送\nActivate scheduled seven-field LINE", 320, 90);
                modelButton = MakeButton("只啟動本地模型橋接\nStart local-model bridge only", 24, 190);
                folderButton = MakeButton("開啟程式資料夾\nOpen package folder", 320, 190);
                Controls.Add(refreshButton);
                Controls.Add(activateButton);
                Controls.Add(modelButton);
                Controls.Add(folderButton);

                status = new Label {
                    Left = 24, Top = 292, Width = 580, Height = 66,
                    Text = "Ready / 就緒",
                    BorderStyle = BorderStyle.FixedSingle,
                    Padding = new Padding(8)
                };
                Controls.Add(status);

                elapsedTimer = new Timer();
                elapsedTimer.Interval = 1000;
                elapsedTimer.Tick += delegate {
                    if (!busy) return;
                    TimeSpan elapsed = DateTime.UtcNow - operationStartedUtc;
                    string progress = LastPowerShellLiveLine;
                    if (String.IsNullOrWhiteSpace(progress))
                        progress = "請保持視窗開啟；即時 log 正在寫入 / Keep this window open; live log is being written";
                    status.Text = operationLabel + "  " + elapsed.ToString(@"mm\:ss") + "\r\n" + progress;
                };

                refreshButton.Click += async delegate {
                    await RunBusyAsync(
                        "更新中 / Refreshing...",
                        async delegate {
                            return await RunPowerShellAsync(
                                "run-v213-local.ps1",
                                "-ProjectRoot \"" + Root + "\" -InstallCloudflared",
                                true);
                        },
                        "更新完成 / Refresh completed",
                        "更新失敗；已顯示詳細原因 / Refresh failed");
                };

                activateButton.Click += async delegate {
                    var answer = MessageBox.Show(
                        "將先執行一次完整刷新與本地模型橋接；只有本地模型公開橋接 health gate 通過，才會正式部署 v2.1.3 Worker，並把每日 08:00 / 21:00 切換成已驗收的七欄格式。\n\n" +
                        "A fresh refresh/model-bridge preflight runs first. Formal activation requires the local-model health gate to pass.\n\nContinue?",
                        "Confirm v2.1.3 activation", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
                    if (answer != DialogResult.Yes) return;

                    await RunBusyAsync(
                        "啟用前刷新 / Preflight refresh...",
                        async delegate {
                            int refresh = await RunPowerShellAsync(
                                "run-v213-local.ps1",
                                "-ProjectRoot \"" + Root + "\" -InstallCloudflared -NoAutoActivation",
                                true);
                            if (refresh != 0) return refresh;
                            operationLabel = "正式啟用中 / Activating...";
                            LastPowerShellLiveLine = "II_PROGRESS activation preflight complete / 啟用前刷新完成";
                            return await RunPowerShellAsync(
                                "activate-v213-seven-field-schedule.ps1",
                                "-ProjectRoot \"" + Root + "\" -ConfirmActivation -RequireLocalModel",
                                true);
                        },
                        "正式啟用完成 / Activation completed",
                        "啟用失敗；Production 保留/rollback 狀態請看詳細訊息 / Activation failed");
                };

                modelButton.Click += async delegate {
                    await RunBusyAsync(
                        "本地模型橋接啟動中 / Starting model bridge...",
                        async delegate {
                            return await RunPowerShellAsync(
                                "run-v213-local-llm-bridge.ps1",
                                "-ProjectRoot \"" + Root + "\" -InstallCloudflared -StopExisting",
                                true);
                        },
                        "本地模型橋接完成 / Model bridge ready",
                        "模型橋接失敗；已顯示詳細原因 / Bridge failed");
                };

                folderButton.Click += delegate {
                    Process.Start("explorer.exe", "\"" + Root + "\"");
                };

                FormClosing += delegate(object sender, FormClosingEventArgs e) {
                    if (!busy) return;
                    e.Cancel = true;
                    MessageBox.Show(
                        "目前仍在執行刷新／啟用程序。為避免留下半完成狀態，請等程序結束後再關閉。\n\nAn operation is still running. Keep the launcher open until it completes.",
                        "Investor Intelligence - Running / 執行中",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Information);
                };
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
                        "Unexpected launcher error / 啟動器非預期錯誤:\r\n\r\n" + ex.Message,
                        "Investor Intelligence - Error / 錯誤",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                }
                finally
                {
                    SetBusy(false, "");
                    if (code == 0)
                        status.Text = successText;
                }
            }

            void SetBusy(bool value, string label)
            {
                busy = value;
                refreshButton.Enabled = !value;
                activateButton.Enabled = !value;
                modelButton.Enabled = !value;
                folderButton.Enabled = !value;
                UseWaitCursor = value;
                if (value)
                {
                    LastPowerShellLiveLine = "II_PROGRESS preparing operation / 準備執行";
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
                    Width = 280,
                    Height = 76,
                    Text = text,
                    UseVisualStyleBackColor = true
                };
            }
        }
    }
}
