import clr, sys
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
from Microsoft.Web.WebView2.Core import CoreWebView2ControllerOptions
from System.Reflection import BindingFlags

t = clr.GetClrType(CoreWebView2ControllerOptions)
for p in t.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance):
    print(f"Property: {p.PropertyType.Name} {p.Name}")
