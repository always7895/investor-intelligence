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
        static string LastPowerShellSummary = "";
        static volatile string LastPowerShellLiveLine = "";

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

        static void PumpStream(
            StreamReader reader,
            string channel,
            StreamWriter writer,
            object sync,
            StringBuilder tail)
        {
            try
            {
                string line;
                while ((line = reader.ReadLine()) != null)
                {
                    lock (sync)
                    {
                        writer.Write(DateTime.Now.ToString("HH:mm:ss.fff"));
                        writer.Write(" [");
                        writer.Write(channel);
                        writer.Write("] ");
                        writer.WriteLine(line);
                        writer.Flush();
                        AppendTail(tail, channel, line);
                    }
                    string safe = UiSafeProgressLine(line);
                    if (!String.IsNullOrEmpty(safe))
                        LastPowerShellLiveLine = safe;
                }
            }
            catch (ObjectDisposedException)
            {
                // Expected when the parent PowerShell process has exited but a
                // descendant retained an inherited pipe handle. The launcher
                // closes the reader after a bounded drain window so the GUI does
                // not remain permanently busy after the real operation is done.
            }
            catch (IOException)
            {
                // Same bounded-drain shutdown path as above.
            }
        }

        static async Task DrainRedirectedStreamsAfterParentExit(
            Process process,
            Task stdoutTask,
            Task stderrTask,
            StreamWriter writer,
            object sync)
        {
            Task drainTask = Task.WhenAll(stdoutTask, stderrTask);
            Task completed = await Task.WhenAny(drainTask, Task.Delay(3000));
            if (completed != drainTask)
            {
                lock (sync)
                {
                    writer.WriteLine("STREAM_DRAIN_TIMEOUT_AFTER_PARENT_EXIT=TRUE");
                    writer.WriteLine("STREAM_DRAIN_ACTION=close_parent_readers_and_continue");
                    writer.Flush();
                }
                try { process.StandardOutput.Close(); } catch { }
                try { process.StandardError.Close(); } catch { }
            }
            try { await drainTask; } catch { }
        }

        static async Task<int> RunPowerShellAsync(string script, string arguments, bool showErrorDialog)
        {
            string path = Path.Combine(Root, script);
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
            string logPath = Path.Combine(
                logRoot,
                DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + "-" + Path.GetFileNameWithoutExtension(script) + ".log");

            LastPowerShellLiveLine = "II_PROGRESS launcher log created / 啟動器即時記錄已建立";
            var tail = new StringBuilder();
            var sync = new object();
            int exitCode = -1;

            using (var stream = new FileStream(logPath, FileMode.Create, FileAccess.Write, FileShare.ReadWrite))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(true)))
            {
                writer.AutoFlush = true;
                writer.WriteLine("Investor Intelligence v" + Version + " live launcher log");
                writer.WriteLine("SCRIPT=" + script);
                writer.WriteLine("STARTED_LOCAL=" + DateTimeOffset.Now.ToString("o"));
                writer.WriteLine("LOG_MODE=LIVE_STREAMING");
                writer.WriteLine("PARENT_EXIT_IS_AUTHORITATIVE=TRUE");
                writer.WriteLine("STREAM_DRAIN_GRACE_SECONDS=3");
                writer.WriteLine("--- LIVE OUTPUT ---");

                var psi = new ProcessStartInfo
                {
                    FileName = "powershell.exe",
                    Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + path + "\" " + arguments,
                    WorkingDirectory = Root,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8
                };

                using (var process = new Process())
                {
                    process.StartInfo = psi;
                    if (!process.Start())
                    {
                        LastPowerShellSummary = "PowerShell process could not be started.\r\nLog / 記錄：" + logPath;
                        writer.WriteLine("PROCESS_START_FAILED");
                        if (showErrorDialog)
                            MessageBox.Show(LastPowerShellSummary, "Investor Intelligence", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        return 3;
                    }

                    writer.WriteLine("PROCESS_ID=" + process.Id);
                    Task stdoutTask = Task.Run(delegate {
                        PumpStream(process.StandardOutput, "OUT", writer, sync, tail);
                    });
                    Task stderrTask = Task.Run(delegate {
                        PumpStream(process.StandardError, "ERR", writer, sync, tail);
                    });

                    // The PowerShell parent process is the authoritative lifetime
                    // of the requested operation. Long-lived gateway/cloudflared
                    // descendants can keep inherited anonymous pipe handles open,
                    // so waiting for EOF before observing parent exit can hang the
                    // GUI forever even after the script has printed PASS and exited.
                    await Task.Run(delegate { process.WaitForExit(); });
                    exitCode = process.ExitCode;
                    lock (sync)
                    {
                        writer.WriteLine("PARENT_PROCESS_EXITED=TRUE");
                        writer.WriteLine("PARENT_EXIT_CODE=" + exitCode);
                        writer.Flush();
                    }
                    await DrainRedirectedStreamsAfterParentExit(process, stdoutTask, stderrTask, writer, sync);
                }

                lock (sync)
                {
                    writer.WriteLine("--- END OUTPUT ---");
                    writer.WriteLine("EXIT_CODE=" + exitCode);
                    writer.WriteLine("FINISHED_LOCAL=" + DateTimeOffset.Now.ToString("o"));
                }
            }

            if (exitCode == 0)
            {
                LastPowerShellSummary = "PASS\r\nLog / 記錄：" + logPath;
                LastPowerShellLiveLine = "INVESTOR_INTELLIGENCE operation PASS";
            }
            else
            {
                string detail;
                lock (sync) { detail = Tail(tail.ToString().Trim(), 6000); }
                LastPowerShellSummary =
                    "Exit code / 結束碼: " + exitCode + "\r\n\r\n" +
                    (String.IsNullOrWhiteSpace(detail) ? "No diagnostic output was returned." : detail) +
                    "\r\n\r\nLog / 完整記錄：\r\n" + logPath;
                LastPowerShellLiveLine = "V213_OPERATION_FAILED; see live log / 請查看即時記錄";
                if (showErrorDialog)
                    MessageBox.Show(LastPowerShellSummary, "Investor Intelligence - Error / 錯誤", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return exitCode;
        }

        static int RunPowerShellCli(string script, string arguments)
        {
            return RunPowerShellAsync(script, arguments, false).GetAwaiter().GetResult();
        }

        [STAThread]
        static int Main(string[] args)
        {
            if (args.Contains("--version"))
            {
                Console.WriteLine("Investor Intelligence " + Version);
                return 0;
            }
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
                Text = "Investor Intelligence v" + Version;
                Width = 640;
                Height = 410;
                StartPosition = FormStartPosition.CenterScreen;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;

                Controls.Add(new Label {
                    Left = 24, Top = 22, Width = 580, Height = 50,
                    Text = "Investor Intelligence v2.1.3\n本地模型 + 七欄 LINE / Local Model + Seven-Field LINE",
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
