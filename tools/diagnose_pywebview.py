import webview
webview.create_window(
    "test",
    url="file:///D:/yihuanpaimai/core/tactical_hud.html",
    width=390,
    height=450,
    frameless=True,
    on_top=True,
    easy_drag=False,
)
webview.start(debug=False)
