# Desktop deployment

The laptop publishes commits to GitHub. The desktop then replaces its checkout
with the published `origin/main` state. This is a source-code deployment, not a
two-way sync: changes made only on the desktop are deliberately destroyed.

## 1. Clone once on the desktop

Install Git, open PowerShell on the desktop, and change to whichever parent
directory should contain the project. Clone without a destination argument;
Git creates `TE2004B_AD26` in the current directory:

```powershell
git clone https://github.com/SilentSammy/TE2004B_AD26.git
cd .\TE2004B_AD26
```

Run the one-step setup. It finds Python 3.11 or asks whether to install it for
the current user without administrator access (the default) or globally with
administrator access. It then creates an environment outside the clone and
installs all dependencies:

```powershell
.\setup-desktop.cmd
```

Keep secrets, recordings, and other desktop-only data outside the cloned
`TE2004B_AD26` directory. Each deployment removes ignored as well as untracked
files from inside the clone. The setup script places the environment under
`%LocalAppData%\TE2004B_AD26\venv`, where the current user can write without
administrator access. It also remembers the clone's actual location there so
remote deployments do not need a hard-coded path.

The files under `device_code` target MicroPython boards and are not included in
`requirements.txt`; modules such as `machine` come from the device firmware.

Start the application from the repository in Command Prompt or PowerShell:

```powershell
.\run-app.cmd
```

To update directly while sitting at the desktop, run:

```powershell
.\update-desktop.cmd
```

## 2. Enable remote deployment

Enable the Windows OpenSSH Server on the desktop, allow it through the firewall,
and configure SSH-key login from the laptop. Verify from the laptop:

```powershell
ssh DESKTOP_USER@DESKTOP_HOST hostname
```

Replace the two placeholders with the desktop's Windows username and hostname
or IP address. Use the same Windows account that ran `setup-desktop.cmd`, since
the saved repository location and current-user Python environment belong to
that account.

## 3. Deploy each laptop update

First commit the wanted changes. From this repository on the laptop, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-to-desktop.ps1 `
    -DesktopHost "DESKTOP_USER@DESKTOP_HOST"
```

The desktop path is read from the location saved by `setup-desktop.cmd`. You
can still override it when needed by adding `-DesktopRepoPath "D:\some\path"`.

The command refuses to run when the laptop has uncommitted changes. Otherwise,
it pushes `main`, connects to the desktop, fetches it, resets tracked files, and
deletes all other files and directories in the desktop checkout. Legacy tracked
Python bytecode changes are ignored by this check because they are generated,
not source changes.

You can save the command as a PowerShell function or alias after substituting
the actual desktop host.
