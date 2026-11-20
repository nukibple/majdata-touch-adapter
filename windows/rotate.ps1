# 旋转显示方向（竖屏/横屏），无需第三方工具
# 用法:
#   powershell -File rotate.ps1 -Orientation portrait
#   powershell -File rotate.ps1 -Orientation landscape
#   powershell -File rotate.ps1 -Orientation portrait -Restore   # 记下当前方向并旋转
param(
    [ValidateSet('portrait', 'landscape', 'inverted', 'left')]
    [string]$Orientation = 'portrait',
    [string]$Device = '\\.\DISPLAY1',
    [switch]$RestoreFile
)

$ErrorActionPreference = 'Stop'

Add-Type @"
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
    public short dmSpecVersion;
    public short dmDriverVersion;
    public short dmSize;
    public short dmDriverExtra;
    public int dmFields;
    public int dmPositionX;
    public int dmPositionY;
    public int dmDisplayOrientation;
    public int dmDisplayFixedOutput;
    public short dmColor;
    public short dmDuplex;
    public short dmYResolution;
    public short dmTTOption;
    public short dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
    public short dmLogPixels;
    public int dmBitsPerPel;
    public int dmPelsWidth;
    public int dmPelsHeight;
    public int dmDisplayFlags;
    public int dmDisplayFrequency;
    public int dmICMMethod;
    public int dmICMIntent;
    public int dmMediaType;
    public int dmDitherType;
    public int dmReserved1;
    public int dmReserved2;
    public int dmPanningWidth;
    public int dmPanningHeight;
}

public class DisplayRotate {
    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern int EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);

    [DllImport("user32.dll", CharSet = CharSet.Ansi)]
    public static extern int ChangeDisplaySettingsEx(string deviceName, ref DEVMODE devMode, IntPtr hwnd, uint flags, IntPtr param);

    public const int ENUM_CURRENT_SETTINGS = -1;
    public const int DMDO_DEFAULT = 0;
    public const int DMDO_90 = 1;
    public const int DMDO_180 = 2;
    public const int DMDO_270 = 3;
    public const int DM_PELSWIDTH = 0x80000;
    public const int DM_PELSHEIGHT = 0x100000;
    public const int DM_DISPLAYORIENTATION = 0x80;
    public const uint CDS_UPDATEREGISTRY = 0x01;

    public static int[] GetCurrent(string device, out int orientation, out int w, out int h) {
        DEVMODE dm = new DEVMODE();
        dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
        if (EnumDisplaySettings(device, ENUM_CURRENT_SETTINGS, ref dm) == 0) {
            orientation = -1; w = 0; h = 0; return new int[] { -1 };
        }
        orientation = dm.dmDisplayOrientation;
        w = dm.dmPelsWidth;
        h = dm.dmPelsHeight;
        return new int[] { 0 };
    }

    public static int SetOrientation(string device, int orientation) {
        DEVMODE dm = new DEVMODE();
        dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
        if (EnumDisplaySettings(device, ENUM_CURRENT_SETTINGS, ref dm) == 0) return -1;

        bool willBePortrait = (orientation == DMDO_90 || orientation == DMDO_270);
        bool isLandscapeMode = dm.dmPelsWidth >= dm.dmPelsHeight;

        // 竖屏时把像素缓冲区设成 高>宽
        if (willBePortrait && isLandscapeMode) {
            int t = dm.dmPelsWidth; dm.dmPelsWidth = dm.dmPelsHeight; dm.dmPelsHeight = t;
            dm.dmFields |= DM_PELSWIDTH | DM_PELSHEIGHT;
        } else if (!willBePortrait && !isLandscapeMode) {
            int t = dm.dmPelsWidth; dm.dmPelsWidth = dm.dmPelsHeight; dm.dmPelsHeight = t;
            dm.dmFields |= DM_PELSWIDTH | DM_PELSHEIGHT;
        }
        dm.dmDisplayOrientation = orientation;
        dm.dmFields |= DM_DISPLAYORIENTATION;
        return ChangeDisplaySettingsEx(device, ref dm, IntPtr.Zero, CDS_UPDATEREGISTRY, IntPtr.Zero);
    }
}
"@

$code = @{
    'portrait'  = 1   # DMDO_90
    'landscape' = 0   # DMDO_DEFAULT
    'left'      = 3   # DMDO_270
    'inverted'  = 2   # DMDO_180
}

$o = 0; $w = 0; $h = 0
[void][DisplayRotate]::GetCurrent($Device, [ref]$o, [ref]$w, [ref]$h)
Write-Host "[*] 当前: ${w}x${h}  orientation=$o"

$rc = [DisplayRotate]::SetOrientation($Device, $code[$Orientation])
Start-Sleep -Milliseconds 800
[void][DisplayRotate]::GetCurrent($Device, [ref]$o, [ref]$w, [ref]$h)

if ($rc -eq 0) {
    Write-Host "[+] 已切换到 $Orientation ：现在 ${w}x${h} orientation=$o" -ForegroundColor Green
} else {
    Write-Host "[!] ChangeDisplaySettingsEx 返回 $rc（0=成功；-2=不支持的模式）" -ForegroundColor Yellow
}
