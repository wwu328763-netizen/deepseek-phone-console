' Phone Console - open the desktop manager window (no terminal window).
' ASCII-only on purpose: Windows Script Host reads .vbs files as ANSI.
Option Explicit

Dim fso, sh, here, exe, pyw, target, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

' Locate everything relative to this script, so moving the folder never breaks it.
here = fso.GetParentFolderName(WScript.ScriptFullName)
exe = fso.BuildPath(here, "ConsolePanel.exe")

sh.CurrentDirectory = here

' Preferred: the WebView2 panel (Gradle-built, ships as ConsolePanel.exe).
If fso.FileExists(exe) Then
    sh.Run """" & exe & """", 1, False
    WScript.Quit 0
End If

' Fallback: the old Tkinter manager (kept for rollback).
target = fso.BuildPath(here, "gui.pyw")
If Not fso.FileExists(target) Then
    MsgBox "Neither ConsolePanel.exe nor gui.pyw was found:" & vbCrLf & here, 16, "Phone Console"
    WScript.Quit 1
End If
pyw = sh.ExpandEnvironmentStrings("%USERPROFILE%") & _
      "\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
cmd = """" & pyw & """ """ & target & """"
sh.Run cmd, 0, False