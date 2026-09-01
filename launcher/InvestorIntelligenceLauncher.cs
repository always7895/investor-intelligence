using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;

namespace InvestorIntelligence
{
    static class Program
    {
        const string Version = "2.1.3";
        static string LastPowerShellSummary = "";

        static string Root
        {
            get { return AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar); }
        }

        static string Tail(string text, int max)
        {
            if (String.IsNullOrEmpty(text)) return "";
            return text.Length <= max ? text : text.Substring(text.Length - max);
        }

        static int RunPowerShell(string script, string arguments)
        {
            string path = Path.Combine(Root, script);
            if (!File.Exists(path))
            {
                LastPowerShellSummary = "Missing script / 找不到腳本:\r\n" + path;
                MessageBox.Show(LastPowerShellSummary, "Investor Intelligence", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }

            string logRoot = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "InvestorIntelligence", "logs", "launcher");
            Directory.CreateDirectory(logRoot);
            string logPath = Path.Combine(logRoot, DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Path.GetFileNameWithoutExtension(script) + ".log");

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

            string stdout = "";
            string stderr = "";
            int exitCode;
            using (var p = Process.Start(psi))
            {
                stdout = p.StandardOutput.ReadToEnd();
                stderr = p.StandardError.ReadToEnd();
                p.WaitForExit();
                exitCode = p.ExitCode;
            }

            File.WriteAllText(logPath,
                "SCRIPT=" + script + Environment.NewLine +
                "EXIT_CODE=" + exitCode + Environment.NewLine +
                "--- STDOUT ---" + Environment.NewLine + stdout + Environment.NewLine +
                "--- STDERR ---" + Environment.NewLine + stderr,
                Encoding.UTF8);

            if (exitCode == 0)
            {
                LastPowerShellSummary = "PASS\r\nLog / 記錄：" + logPath;
            }
            else
            {
                string detail = Tail((stderr + "\r\n" + stdout).Trim(), 5000);
                LastPowerShellSummary =
                    "Exit code / 結束碼: " + exitCode + "\r\n\r\n" +
                    (String.IsNullOrWhiteSpace(detail) ? "No diagnostic output was returned." : detail) +
                    "\r\n\r\nLog / 完整記錄：\r\n" + logPath;
                MessageBox.Show(LastPowerShellSummary, "Investor Intelligence - Error / 錯誤", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return exitCode;
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
                return RunPowerShell("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared");
            if (args.Contains("--activate-schedule"))
            {
                int refresh = RunPowerShell("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared -NoAutoActivation");
                if (refresh != 0) return refresh;
                return RunPowerShell("activate-v213-seven-field-schedule.ps1", "-ProjectRoot \"" + Root + "\" -ConfirmActivation");
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
            return 0;
        }

        sealed class MainForm : Form
        {
            readonly Label status;

            public MainForm()
            {
                Text = "Investor Intelligence v" + Version;
                Width = 640;
                Height = 390;
                StartPosition = FormStartPosition.CenterScreen;
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;

                Controls.Add(new Label {
                    Left = 24, Top = 22, Width = 580, Height = 50,
                    Text = "Investor Intelligence v2.1.3\n本地模型 + 七欄 LINE / Local Model + Seven-Field LINE",
                    Font = new System.Drawing.Font("Segoe UI", 13F, System.Drawing.FontStyle.Bold)
                });

                Controls.Add(Button("啟動本地模型並更新資料\nStart local model + refresh", 24, 90, delegate {
                    status.Text = "執行中 / Running...";
                    int code = RunPowerShell("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared");
                    status.Text = code == 0 ? "更新完成 / Refresh completed" : "更新失敗；已顯示詳細原因 / Refresh failed";
                }));

                Controls.Add(Button("正式啟用 08:00 / 21:00 七欄推送\nActivate scheduled seven-field LINE", 320, 90, delegate {
                    var answer = MessageBox.Show(
                        "將先執行一次完整刷新與本地模型橋接，再正式部署 v2.1.3 Worker，並把每日 08:00 / 21:00 切換成已驗收的七欄格式。\n\n" +
                        "A fresh refresh/model-bridge preflight runs first, then the accepted seven-field schedule is deployed.\n\nContinue?",
                        "Confirm v2.1.3 activation", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
                    if (answer != DialogResult.Yes) return;
                    status.Text = "先刷新資料與模型橋接 / Refreshing before activation...";
                    int refresh = RunPowerShell("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared -NoAutoActivation");
                    if (refresh != 0)
                    {
                        status.Text = "前置刷新失敗；Production 未切換 / Preflight refresh failed";
                        return;
                    }
                    status.Text = "正式啟用中 / Activating...";
                    int code = RunPowerShell("activate-v213-seven-field-schedule.ps1", "-ProjectRoot \"" + Root + "\" -ConfirmActivation");
                    status.Text = code == 0 ? "正式啟用完成 / Activation completed" : "啟用失敗；已顯示 rollback/錯誤詳細資料 / Activation failed";
                }));

                Controls.Add(Button("只啟動本地模型橋接\nStart local-model bridge only", 24, 190, delegate {
                    status.Text = "本地模型橋接啟動中 / Starting model bridge...";
                    int code = RunPowerShell("run-v213-local-llm-bridge.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared -StopExisting");
                    status.Text = code == 0 ? "本地模型橋接完成；正式 Worker 路由會在刷新/啟用時更新 / Model bridge ready" : "模型橋接失敗；已顯示詳細原因 / Bridge failed";
                }));

                Controls.Add(Button("開啟程式資料夾\nOpen package folder", 320, 190, delegate {
                    Process.Start("explorer.exe", "\"" + Root + "\"");
                }));

                status = new Label {
                    Left = 24, Top = 292, Width = 580, Height = 45,
                    Text = "Ready / 就緒",
                    BorderStyle = BorderStyle.FixedSingle,
                    Padding = new Padding(8)
                };
                Controls.Add(status);
            }

            Button Button(string text, int left, int top, EventHandler click)
            {
                var b = new Button { Left = left, Top = top, Width = 280, Height = 76, Text = text, UseVisualStyleBackColor = true };
                b.Click += click;
                return b;
            }
        }
    }
}
