using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace InvestorIntelligence
{
    static class Program
    {
        const string Version = "2.1.3";

        static string Root
        {
            get { return AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar); }
        }

        static int RunPowerShell(string script, string arguments)
        {
            string path = Path.Combine(Root, script);
            if (!File.Exists(path))
            {
                MessageBox.Show("Missing script / 找不到腳本:\n" + path, "Investor Intelligence", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }
            var psi = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + path + "\" " + arguments,
                WorkingDirectory = Root,
                UseShellExecute = false
            };
            using (var p = Process.Start(psi))
            {
                p.WaitForExit();
                return p.ExitCode;
            }
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
                    @"scripts\build_v213_scheduled_top20_report.py"
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
            {
                return RunPowerShell("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared");
            }
            if (args.Contains("--activate-schedule"))
            {
                return RunPowerShell("activate-v213-seven-field-schedule.ps1",
                    "-ProjectRoot \"" + Root + "\" -ConfirmActivation");
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

                var title = new Label {
                    Left = 24, Top = 22, Width = 580, Height = 50,
                    Text = "Investor Intelligence v2.1.3\n本地模型 + 七欄 LINE / Local Model + Seven-Field LINE",
                    Font = new System.Drawing.Font("Segoe UI", 13F, System.Drawing.FontStyle.Bold)
                };
                Controls.Add(title);

                var run = Button("啟動本地模型並更新資料\nStart local model + refresh", 24, 90, delegate {
                    int code = RunPowerShell("run-v213-local.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared");
                    status.Text = code == 0 ? "更新完成 / Refresh completed" : "更新失敗 / Refresh failed: " + code;
                });
                Controls.Add(run);

                var activate = Button("正式啟用 08:00 / 21:00 七欄推送\nActivate scheduled seven-field LINE", 320, 90, delegate {
                    var answer = MessageBox.Show(
                        "這會正式部署 v2.1.3 Worker 並把每日 08:00 / 21:00 切換成已驗收的七欄格式。\n\n" +
                        "This formally deploys the v2.1.3 Worker and activates the accepted seven-field schedule.\n\nContinue?",
                        "Confirm v2.1.3 activation", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
                    if (answer != DialogResult.Yes) return;
                    int code = RunPowerShell("activate-v213-seven-field-schedule.ps1",
                        "-ProjectRoot \"" + Root + "\" -ConfirmActivation");
                    status.Text = code == 0 ? "正式啟用完成 / Activation completed" : "啟用失敗；請查看 rollback 訊息 / Activation failed: " + code;
                });
                Controls.Add(activate);

                var model = Button("只啟動本地模型橋接\nStart local-model bridge only", 24, 190, delegate {
                    int code = RunPowerShell("run-v213-local-llm-bridge.ps1", "-ProjectRoot \"" + Root + "\" -InstallCloudflared");
                    status.Text = code == 0 ? "本地模型橋接完成 / Model bridge ready" : "模型橋接失敗 / Bridge failed: " + code;
                });
                Controls.Add(model);

                var folder = Button("開啟程式資料夾\nOpen package folder", 320, 190, delegate {
                    Process.Start("explorer.exe", "\"" + Root + "\"");
                });
                Controls.Add(folder);

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
                var b = new Button {
                    Left = left, Top = top, Width = 280, Height = 76,
                    Text = text, UseVisualStyleBackColor = true
                };
                b.Click += click;
                return b;
            }
        }
    }
}
