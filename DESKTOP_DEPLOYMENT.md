# Desktop deployment

The laptop publishes commits to GitHub. The desktop then replaces its checkout
with the published `origin/main` state. This is a source-code deployment, not a
two-way sync: changes made only on the desktop are deliberately destroyed.

## 1. Clone once on the desktop

Install Git, open PowerShell on the desktop, and choose a path that does not
already exist:

```powershell
git clone https://github.com/SilentSammy/TE2004B_AD26.git C:\Apps\TE2004B_AD26
cd C:\Apps\TE2004B_AD26
```

Keep virtual environments, secrets, recordings, and other desktop-only data
outside `C:\Apps\TE2004B_AD26`. Each deployment removes ignored as well as
untracked files from inside the clone.

Create the desktop's Python 3.11 environment outside the clone and install the
host application dependencies:

```powershell
py -3.11 -m venv C:\Apps\TE2004B_AD26-venv
C:\Apps\TE2004B_AD26-venv\Scripts\python.exe -m pip install --upgrade pip
C:\Apps\TE2004B_AD26-venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

The files under `device_code` target MicroPython boards and are not included in
`requirements.txt`; modules such as `machine` come from the device firmware.

To update directly while sitting at the desktop, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-desktop-repo.ps1
```

## 2. Enable remote deployment

Enable the Windows OpenSSH Server on the desktop, allow it through the firewall,
and configure SSH-key login from the laptop. Verify from the laptop:

```powershell
ssh DESKTOP_USER@DESKTOP_HOST hostname
```

Replace the two placeholders with the desktop's Windows username and hostname
or IP address.

## 3. Deploy each laptop update

First commit the wanted changes. From this repository on the laptop, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-to-desktop.ps1 `
    -DesktopHost "DESKTOP_USER@DESKTOP_HOST" `
    -DesktopRepoPath "C:\Apps\TE2004B_AD26"
```

The command refuses to run when the laptop has uncommitted changes. Otherwise,
it pushes `main`, connects to the desktop, fetches it, resets tracked files, and
deletes all other files and directories in the desktop checkout. Legacy tracked
Python bytecode changes are ignored by this check because they are generated,
not source changes.

You can save the command as a PowerShell function or alias after substituting
the actual desktop host and path.
