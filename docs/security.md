# Security

PythonKni includes tools that inspect local processes, scan local networks, read saved WiFi profile names and manipulate files.

Use these tools only on systems you own or where you have explicit authorization.

## Secrets

Do not hard-code API keys in source code. Use environment variables instead.

VirusTotal integration reads:

```text
VIRUSTOTAL_API_KEY
```

If a key was previously committed or shared, revoke it and create a new one.
