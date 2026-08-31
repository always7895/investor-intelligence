using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace InvestorIntelligence
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                if (HasFlag(args, "--self-test"))
                {
                    return 0;
                }

                string appRoot = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar
                );
                string runScript = Path.Combine(appRoot, "run-local.ps1");
                if (!File.Exists(runScript))
                {
                    throw new FileNotFoundException("Installed run-local.ps1 is missing.", runScript);
                }

                DirectoryInfo appDirectory = new DirectoryInfo(appRoot);
                if (appDirectory.Parent == null || appDirectory.Parent.Parent == null)
                {
                    throw new InvalidOperationException("Unable to resolve the Investor Intelligence installation root.");
                }
                string baseRoot = appDirectory.Parent.Parent.FullName;
                string scheduledSlot = "manual";
                bool noOpen = false;
                bool noSync = false;
                bool synthetic = false;

                for (int index = 0; index < args.Length; index++)
                {
                    string value = args[index] ?? "";
                    if (String.Equals(value, "--base-root", StringComparison.OrdinalIgnoreCase))
                    {
                        if (index + 1 >= args.Length)
                        {
                            throw new ArgumentException("--base-root requires a path.");
                        }
                        baseRoot = Path.GetFullPath(args[++index]);
                    }
                    else if (String.Equals(value, "--scheduled-slot", StringComparison.OrdinalIgnoreCase))
                    {
                        if (index + 1 >= args.Length)
                        {
                            throw new ArgumentException("--scheduled-slot requires a value.");
                        }
                        scheduledSlot = args[++index];
                        if (scheduledSlot != "manual" && scheduledSlot != "morning" && scheduledSlot != "evening")
                        {
                            throw new ArgumentException("--scheduled-slot must be manual, morning or evening.");
                        }
                    }
                    else if (String.Equals(value, "--no-open", StringComparison.OrdinalIgnoreCase))
                    {
                        noOpen = true;
                    }
                    else if (String.Equals(value, "--no-sync", StringComparison.OrdinalIgnoreCase))
                    {
                        noSync = true;
                    }
                    else if (String.Equals(value, "--synthetic", StringComparison.OrdinalIgnoreCase))
                    {
                        synthetic = true;
                    }
                    else
                    {
                        throw new ArgumentException("Unknown argument: " + value);
                    }
                }

                string systemPowerShell = Path.Combine(
                    Environment.SystemDirectory,
                    "WindowsPowerShell",
                    "v1.0",
                    "powershell.exe"
                );
                string powershell = File.Exists(systemPowerShell) ? systemPowerShell : "powershell.exe";

                StringBuilder arguments = new StringBuilder();
                AddArgument(arguments, "-NoProfile");
                AddArgument(arguments, "-ExecutionPolicy");
                AddArgument(arguments, "Bypass");
                AddArgument(arguments, "-File");
                AddArgument(arguments, runScript);
                AddArgument(arguments, "-BaseInstallRoot");
                AddArgument(arguments, baseRoot);
                AddArgument(arguments, "-ScheduledSlot");
                AddArgument(arguments, scheduledSlot);
                if (scheduledSlot != "manual")
                {
                    AddArgument(arguments, "-NonInteractive");
                }
                if (!noOpen && scheduledSlot == "manual")
                {
                    AddArgument(arguments, "-OpenReports");
                }
                if (noSync)
                {
                    AddArgument(arguments, "-NoSync");
                }
                if (synthetic)
                {
                    AddArgument(arguments, "-Synthetic");
                }

                ProcessStartInfo info = new ProcessStartInfo();
                info.FileName = powershell;
                info.Arguments = arguments.ToString();
                info.WorkingDirectory = appRoot;
                info.UseShellExecute = false;
                info.CreateNoWindow = false;

                using (Process process = Process.Start(info))
                {
                    if (process == null)
                    {
                        throw new InvalidOperationException("Unable to start PowerShell.");
                    }
                    process.WaitForExit();
                    if (process.ExitCode != 0)
                    {
                        MessageBox.Show(
                            "Investor Intelligence 執行失敗，exit code " + process.ExitCode + "。",
                            "Investor Intelligence v2.1.0",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Error
                        );
                    }
                    return process.ExitCode;
                }
            }
            catch (Exception error)
            {
                MessageBox.Show(
                    error.Message,
                    "Investor Intelligence v2.1.0",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 1;
            }
        }

        private static bool HasFlag(string[] args, string flag)
        {
            foreach (string value in args)
            {
                if (String.Equals(value, flag, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
            return false;
        }

        private static void AddArgument(StringBuilder builder, string value)
        {
            if (builder.Length > 0)
            {
                builder.Append(' ');
            }
            builder.Append('"');
            builder.Append((value ?? "").Replace("\"", "\\\""));
            builder.Append('"');
        }
    }
}
