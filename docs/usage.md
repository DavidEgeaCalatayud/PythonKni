# Usage

Run the application in development mode:

```powershell
python main.py
```

Build the executable:

```powershell
pyinstaller PythonKni.spec
```

Runtime files are stored in the user profile, not in the repository:

```text
%LOCALAPPDATA%\PythonKni\
```
