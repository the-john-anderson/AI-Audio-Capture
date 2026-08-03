using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("AI Audio Capture")]
[assembly: System.Reflection.AssemblyDescription("Inicializador do AI Audio Capture")]
[assembly: System.Reflection.AssemblyCompany("AI Audio Capture")]
[assembly: System.Reflection.AssemblyProduct("AI Audio Capture")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

namespace AiAudioCaptureLauncher
{
    internal static class Program
    {
        private const string ApplicationTitle = "AI Audio Capture";

#if PREFER_LIGHT
        private static readonly string[] RelativeTargets =
        {
            @"dist\AI-Audio-Capture\AI-Audio-Capture.exe",
            @"dist\AI-Audio-Capture-full\AI-Audio-Capture-full.exe",
        };
#else
        private static readonly string[] RelativeTargets =
        {
            @"dist\AI-Audio-Capture-full\AI-Audio-Capture-full.exe",
            @"dist\AI-Audio-Capture\AI-Audio-Capture.exe",
        };
#endif

        [STAThread]
        private static int Main(string[] args)
        {
            string repositoryRoot = AppDomain.CurrentDomain.BaseDirectory;
            string target = FindTarget(repositoryRoot);

            if (target == null)
            {
                ShowError(
                    "O aplicativo empacotado não foi encontrado.\n\n" +
                    "Execute este comando na raiz do repositório:\n" +
                    @".\build\build_exe.ps1 -Full -Clean"
                );
                return 2;
            }

            if (args.Length == 1 &&
                string.Equals(args[0], "--check", StringComparison.OrdinalIgnoreCase))
            {
                Console.WriteLine(target);
                return 0;
            }

            try
            {
                using (Process application = Process.Start(
                    new ProcessStartInfo
                    {
                        FileName = target,
                        WorkingDirectory = repositoryRoot,
                        UseShellExecute = false,
                        CreateNoWindow = false,
                    }))
                {
                    application.WaitForExit();
                    return application.ExitCode;
                }
            }
            catch (Exception exception)
            {
                ShowError(
                    "Não foi possível abrir o aplicativo.\n\n" + exception.Message
                );
                return 1;
            }
        }

        private static string FindTarget(string repositoryRoot)
        {
            foreach (string relativeTarget in RelativeTargets)
            {
                string target = Path.GetFullPath(
                    Path.Combine(repositoryRoot, relativeTarget)
                );
                if (File.Exists(target))
                {
                    return target;
                }
            }

            return null;
        }

        private static void ShowError(string message)
        {
            Console.Error.WriteLine(message);
            MessageBox.Show(
                message,
                ApplicationTitle,
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
    }
}
