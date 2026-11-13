"""The page draws in the title bar's row; the OS keeps the caption buttons (Windows only).

The form's client area is stretched over the caption (``WM_NCCALCSIZE``) and
the DWM frame is extended into it (``DwmExtendFrameIntoClientArea``), so DWM
still draws the real minimize / maximize / close buttons there. The WebView2
control is clipped (``SetWindowRgn``) where they are and along the top resize
edge, so the form receives the mouse there: ``DwmDefWindowProc`` hit-tests the
buttons (hover, snap layouts) and ``WM_NCHITTEST`` gives the top edge. The
rest of the row is the page's: ``app-region: drag`` makes WebView2 treat it as
the caption (drag, double-click, system menu). Measured in Issue #172.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

_log = logging.getLogger(__name__)

LRESULT = ctypes.c_ssize_t

WM_ACTIVATE = 0x0006
WM_WINDOWPOSCHANGING = 0x0046
WM_WINDOWPOSCHANGED = 0x0047
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_DPICHANGED = 0x02E0
HTCLIENT, HTCAPTION, HTTOP, HTTOPLEFT, HTTOPRIGHT = 1, 2, 12, 13, 14
SM_CYFRAME, SM_CYCAPTION, SM_CXPADDEDBORDER = 33, 4, 92
DWMWA_CAPTION_BUTTON_BOUNDS = 5
RGN_DIFF = 4
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
SWP_FRAMECHANGED = 0x0020
#: Id of this subclass on the form (`SetWindowSubclass`).
SUBCLASS_ID = 125


class MARGINS(ctypes.Structure):
    """``MARGINS`` of ``DwmExtendFrameIntoClientArea``."""

    _fields_ = [
        ("left", ctypes.c_int),
        ("right", ctypes.c_int),
        ("top", ctypes.c_int),
        ("bottom", ctypes.c_int),
    ]


class WINDOWPOS(ctypes.Structure):
    """``WINDOWPOS`` of ``WM_WINDOWPOSCHANGING``."""

    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("insert_after", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    """``NCCALCSIZE_PARAMS`` of ``WM_NCCALCSIZE``."""

    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi")
    _comctl32 = ctypes.WinDLL("comctl32")
    SUBCLASSPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        ctypes.c_size_t,
        ctypes.c_size_t,
    )
    _comctl32.SetWindowSubclass.argtypes = [
        wintypes.HWND,
        SUBCLASSPROC,
        ctypes.c_size_t,
        ctypes.c_size_t,
    ]
    _comctl32.SetWindowSubclass.restype = wintypes.BOOL
    _comctl32.DefSubclassProc.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _comctl32.DefSubclassProc.restype = LRESULT
    _dwmapi.DwmDefWindowProc.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        ctypes.POINTER(LRESULT),
    ]
    _dwmapi.DwmExtendFrameIntoClientArea.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(MARGINS),
    ]
    _dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    _user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _gdi32.CreateRectRgn.restype = wintypes.HRGN
    _gdi32.CombineRgn.argtypes = [
        wintypes.HRGN,
        wintypes.HRGN,
        wintypes.HRGN,
        ctypes.c_int,
    ]
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]


def _metric(index: int, hwnd: int) -> int:
    """Return a system metric at the window's DPI."""
    return _user32.GetSystemMetricsForDpi(index, _user32.GetDpiForWindow(hwnd) or 96)


def resize_border(hwnd: int) -> int:
    """Return the height of the top resize edge, as the frame's.

    Parameters
    ----------
    hwnd : int
        The form's handle.

    Returns
    -------
    int
        ``SM_CYFRAME + SM_CXPADDEDBORDER`` in physical pixels.
    """
    return _metric(SM_CYFRAME, hwnd) + _metric(SM_CXPADDEDBORDER, hwnd)


def caption_height(hwnd: int) -> int:
    """Return the height of the caption, the top resize edge included.

    Parameters
    ----------
    hwnd : int
        The form's handle.

    Returns
    -------
    int
        Height in physical pixels.
    """
    return _metric(SM_CYCAPTION, hwnd) + resize_border(hwnd)


def caption_buttons(hwnd: int) -> wintypes.RECT:
    """Return the caption buttons' rectangle in client coordinates.

    Parameters
    ----------
    hwnd : int
        The form's handle.

    Returns
    -------
    ctypes.wintypes.RECT
        ``DWMWA_CAPTION_BUTTON_BOUNDS``, moved from window coordinates.
    """
    bounds = wintypes.RECT()
    _dwmapi.DwmGetWindowAttribute(
        hwnd,
        DWMWA_CAPTION_BUTTON_BOUNDS,
        ctypes.byref(bounds),
        ctypes.sizeof(bounds),
    )
    window = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(window))
    origin = wintypes.POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(origin))
    dx, dy = window.left - origin.x, window.top - origin.y
    return wintypes.RECT(
        bounds.left + dx, bounds.top + dy, bounds.right + dx, bounds.bottom + dy
    )


def geometry_script(buttons_width: int, row_height: int) -> str:
    """Return the script that tells a page the caption's geometry.

    Parameters
    ----------
    buttons_width : int
        Width of the caption buttons from the window's right edge, in
        physical pixels.
    row_height : int
        Height of the page's row beside them, in physical pixels.

    Returns
    -------
    str
        Sets ``--caption-buttons-width`` and ``--caption-row`` in CSS pixels
        on the root element (`titlebar.css` reads them).
    """
    return (
        "document.documentElement.style.setProperty('--caption-buttons-width',"
        f"({buttons_width} / devicePixelRatio) + 'px');"
        "document.documentElement.style.setProperty('--caption-row',"
        f"({row_height} / devicePixelRatio) + 'px');"
    )


class TitleBar:
    """Gives a pywebview window's caption row to its page.

    Call `attach` before the window starts; the rest runs on the window's
    events.
    """

    def __init__(self) -> None:
        self._window = None
        self._proc = None  # the subclass procedure, kept alive for the window's life
        self._hwnd = 0
        self._control = None
        self._buttons_width = 0
        self._row_height = 0
        # Whether the window was neither maximized nor minimized at the last
        # WM_WINDOWPOSCHANGED, and the size to keep while WinForms restores.
        self._normal = True
        self._keep: tuple[int, int] | None = None

    def attach(self, window: object) -> None:
        """Install the title bar once the window is shown; off Windows, nothing.

        Parameters
        ----------
        window : webview.Window
            The window, not started yet.
        """
        if sys.platform != "win32":
            return
        self._window = window
        window.events.before_show += self._before_show
        window.events.shown += self._shown
        window.events.loaded += self._loaded

    def _before_show(self) -> None:
        """Let WebView2 hand `app-region` to the OS before the first page loads."""
        self._invoke(self._allow_regions)

    def _shown(self) -> None:
        """Take over the caption; pywebview calls this in a thread of its own."""
        self._invoke(self._install)

    def _loaded(self) -> None:
        """Tell a newly loaded page the caption's geometry."""
        self._invoke(self._tell_page)

    def _invoke(self, action: object) -> None:
        """Run `action` on the UI thread; log what fails."""
        try:
            from System import Action

            self._window.native.Invoke(Action(action))
        except Exception:  # noqa: BLE001 - logged; the window keeps working without it
            _log.exception("title bar")

    def _allow_regions(self) -> None:
        """Turn on ``IsNonClientRegionSupportEnabled``, now or once WebView2 is ready."""
        control = self._window.native.browser.webview
        if control.CoreWebView2 is not None:
            control.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True
        else:
            control.CoreWebView2InitializationCompleted += self._on_initialized

    def _on_initialized(self, sender: object, args: object) -> None:
        """Turn on ``IsNonClientRegionSupportEnabled`` once WebView2 is ready."""
        if args.IsSuccess:
            sender.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True

    def _install(self) -> None:
        """Subclass the form and lay the caption over the page; on the UI thread."""
        from System.Drawing import Color

        form = self._window.native
        # Black is transparent where the DWM frame is extended.
        form.BackColor = Color.Black
        self._hwnd = form.Handle.ToInt64()
        self._control = form.browser.webview
        self._proc = SUBCLASSPROC(self._wndproc)
        _comctl32.SetWindowSubclass(self._hwnd, self._proc, SUBCLASS_ID, 0)
        self._extend()
        _user32.SetWindowPos(
            self._hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )
        self._clip()

    def _extend(self) -> None:
        """Extend the DWM frame over the caption, where DWM draws the buttons."""
        margins = MARGINS(0, 0, caption_height(self._hwnd), 0)
        _dwmapi.DwmExtendFrameIntoClientArea(self._hwnd, ctypes.byref(margins))

    def _clip(self) -> None:
        """Place and clip the WebView2 control, and tell the page the caption's geometry.

        Not maximized, the control is clipped off the top resize edge.
        Maximized, the window hangs over the screen by its frame, and the
        form's padding moves the control below it. Either way it is clipped
        off the caption buttons.
        """
        from System.Windows.Forms import Padding

        hwnd = self._hwnd
        zoomed = bool(_user32.IsZoomed(hwnd))
        border = resize_border(hwnd)
        pad = border if zoomed else 0
        form = self._window.native
        if form.Padding.Top != pad:
            form.Padding = Padding(0, pad, 0, 0)
        client = wintypes.RECT()
        _user32.GetClientRect(hwnd, ctypes.byref(client))
        top = 0 if zoomed else border
        buttons = caption_buttons(hwnd)
        # In the control's coordinates: the client's, less the padding.
        region = _gdi32.CreateRectRgn(0, top - pad, client.right, client.bottom - pad)
        hole = _gdi32.CreateRectRgn(buttons.left, -pad, client.right, buttons.bottom - pad)
        _gdi32.CombineRgn(region, region, hole, RGN_DIFF)
        _gdi32.DeleteObject(hole)
        # The system owns the region from here on.
        _user32.SetWindowRgn(self._control.Handle.ToInt64(), region, True)
        self._buttons_width = client.right - buttons.left
        self._row_height = buttons.bottom - border
        self._tell_page()

    def _tell_page(self) -> None:
        """Hand the caption's geometry to the page; on the UI thread, without waiting."""
        core = self._control.CoreWebView2 if self._control is not None else None
        if core is not None:
            core.ExecuteScriptAsync(geometry_script(self._buttons_width, self._row_height))

    def _wndproc(
        self, hwnd: int, msg: int, wparam: int, lparam: int, _id: int, _data: int
    ) -> int:
        """Handle the form's messages before WinForms does."""
        try:
            return self._handle(hwnd, msg, wparam, lparam)
        except Exception:  # noqa: BLE001 - logged; the default handling follows
            _log.exception("title bar message %#x", msg)
            return _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)

    def _handle(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """Return the result of one message (`_wndproc`)."""
        result = LRESULT(0)
        if _dwmapi.DwmDefWindowProc(hwnd, msg, wparam, lparam, ctypes.byref(result)):
            return result.value
        if msg == WM_NCCALCSIZE and wparam:
            params = NCCALCSIZE_PARAMS.from_address(lparam)
            top = params.rgrc[0].top
            _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
            # Keep the left, right and bottom frame; drop the caption, also
            # when maximized: DwmDefWindowProc hit-tests the caption buttons
            # only while the client area starts at the window's top (`_clip`
            # moves the page below what hangs over the screen).
            params.rgrc[0].top = top
            return 0
        if msg == WM_NCHITTEST:
            return self._hit(hwnd, lparam)
        if msg in (WM_ACTIVATE, WM_DPICHANGED):
            self._extend()
        if msg == WM_WINDOWPOSCHANGING and self._keep is not None:
            pos = WINDOWPOS.from_address(lparam)
            if not pos.flags & SWP_NOSIZE:
                # WinForms restores the client size it kept, with a standard
                # frame (the caption included) around it: keep the size the
                # OS restored instead.
                pos.cx, pos.cy = self._keep
        if msg == WM_WINDOWPOSCHANGED:
            return self._moved(hwnd, msg, wparam, lparam)
        return _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)

    def _hit(self, hwnd: int, lparam: int) -> int:
        """Hit-test the top resize edge and the caption, where the page is clipped off."""
        hit = _comctl32.DefSubclassProc(hwnd, WM_NCHITTEST, 0, lparam)
        if hit != HTCLIENT:
            return hit
        point = wintypes.POINT(
            ctypes.c_short(lparam & 0xFFFF).value,
            ctypes.c_short((lparam >> 16) & 0xFFFF).value,
        )
        _user32.ScreenToClient(hwnd, ctypes.byref(point))
        border = resize_border(hwnd)
        if not _user32.IsZoomed(hwnd) and point.y < border:
            client = wintypes.RECT()
            _user32.GetClientRect(hwnd, ctypes.byref(client))
            if point.x < border * 2:
                return HTTOPLEFT
            if point.x >= client.right - border * 2:
                return HTTOPRIGHT
            return HTTOP
        if point.y < caption_height(hwnd):
            return HTCAPTION
        return hit

    def _moved(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """Keep the restored size through WinForms, then clip the page again.

        WinForms handles a restore in ``WM_WINDOWPOSCHANGED`` (after the
        ``WM_SIZE`` that ``DefWindowProc`` sends from it) and resizes the
        window to the client size it kept while maximized, with a standard
        frame around it; `_handle` puts the size the OS restored back into
        the ``WM_WINDOWPOSCHANGING`` that this causes.
        """
        normal = not _user32.IsZoomed(hwnd) and not _user32.IsIconic(hwnd)
        outer = self._keep is None
        if outer and normal and not self._normal:
            window = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(window))
            self._keep = (window.right - window.left, window.bottom - window.top)
        self._normal = normal
        try:
            result = _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)
        finally:
            if outer:
                self._keep = None
        self._clip()
        return result
