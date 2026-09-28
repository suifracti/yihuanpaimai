using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

namespace ArchitectureV2.NativeHost
{
    public class WebView2ShellResult
    {
        public bool Initialized { get; set; }
        public string RuntimeVersion { get; set; } = string.Empty;
        public double InitElapsedMs { get; set; }
        public string UserDataFolder { get; set; } = string.Empty;
        public string HostModel { get; set; } = "Pure .NET 8 Win32/DirectComposition Controller (zero pythonnet interop overhead)";
        public string CapabilityNote { get; set; } = string.Empty;
    }

    public static class WebView2ShellProbe
    {
        public static Task<WebView2ShellResult> RunAsync()
        {
            var tcs = new TaskCompletionSource<WebView2ShellResult>();

            var staThread = new Thread(() =>
            {
                var result = new WebView2ShellResult();
                var sw = Stopwatch.StartNew();
                string tempDir = Path.Combine(Path.GetTempPath(), "nte_spike_wv2_" + Guid.NewGuid().ToString("N"));
                result.UserDataFolder = tempDir;

                Form? form = null;
                try
                {
                    form = new Form
                    {
                        Width = 320,
                        Height = 240,
                        ShowInTaskbar = false,
                        FormBorderStyle = FormBorderStyle.None,
                        StartPosition = FormStartPosition.Manual,
                        Location = new Point(50, 50)
                    };

                    form.Shown += async (s, e) =>
                    {
                        try
                        {
                            var env = await CoreWebView2Environment.CreateAsync(null, tempDir);
                            result.RuntimeVersion = env.BrowserVersionString;
                            sw.Stop();

                            result.Initialized = true;
                            result.InitElapsedMs = sw.Elapsed.TotalMilliseconds;
                            result.CapabilityNote = $"CoreWebView2Environment initialized successfully. Evergreen WebView2 runtime v{env.BrowserVersionString} ready for native hosting.";

                            try
                            {
                                var controller = await env.CreateCoreWebView2ControllerAsync(form.Handle);
                                if (controller != null)
                                {
                                    result.HostModel = "Pure .NET 8 Win32 Controller (Active HWND Controller Created)";
                                }
                            }
                            catch (Exception ex)
                            {
                                result.CapabilityNote += $" (Controller HWND note: {ex.Message})";
                            }

                            form.Close();
                            tcs.TrySetResult(result);
                        }
                        catch (Exception ex)
                        {
                            sw.Stop();
                            result.Initialized = false;
                            result.InitElapsedMs = sw.Elapsed.TotalMilliseconds;
                            result.CapabilityNote = $"Environment initialization failed: {ex.Message}";
                            form.Close();
                            tcs.TrySetResult(result);
                        }
                    };

                    Application.Run(form);
                }
                catch (Exception ex)
                {
                    result.Initialized = false;
                    result.CapabilityNote = $"Form/Thread exception: {ex.Message}";
                    tcs.TrySetResult(result);
                }
                finally
                {
                    try
                    {
                        if (Directory.Exists(tempDir))
                        {
                            Directory.Delete(tempDir, true);
                        }
                    }
                    catch { }
                }
            })
            {
                IsBackground = true
            };

            staThread.SetApartmentState(ApartmentState.STA);
            staThread.Start();

            return tcs.Task;
        }
    }
}
