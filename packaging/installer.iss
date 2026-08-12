; Inno Setup script for LakituAI
; Build with: ISCC.exe packaging\installer.iss
; Requires the PyInstaller onedir build at dist\LakituAI\

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "LakituAI"
#define MyAppExeName "LakituAI.exe"
#define MyAppPublisher "LakituAI"

[Setup]
; Stable AppId so re-running the installer upgrades an existing install.
AppId={{D29F6C4E-8A3B-4B2F-9C1E-LAKITUAI00001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename=LakituAI-Setup
OutputDir=installer-output
SetupIconFile=..\packaging\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The uninstaller deletes whatever the user selects (data/model) via [Code].
; Files that persist in {app} are removed automatically by Inno Setup.
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller onedir output (all DLLs, PYD, assets, config)
Source: "..\dist\LakituAI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Helper script for optional Ollama setup. Copied to {tmp} during install so
; the [Run] step below can execute it (no `dontcopy`, which needs a manual
; ExtractTemporaryFile call).
Source: "installer\install_ollama.ps1"; DestDir: "{tmp}"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; Optional: install Ollama + qwen3:4b (only if the user checked it)
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{tmp}\install_ollama.ps1"""; Flags: runhidden; StatusMsg: "Setting up Ollama and chat model..."; Check: ShouldInstallOllama

[Code]
var
  OllamaPage: TWizardPage;
  OllamaCheckbox: TNewCheckBox;
  VramWarningShown: Boolean;
  UninstallDataCheckbox: TNewCheckBox;
  UninstallModelCheckbox: TNewCheckBox;

function GetTotalVramMb(): Integer;
var
  TmpFile, Line: String;
  ResultCode: Integer;
  List: TStringList;
  Mb: Int64;
  Wmi, Item: Variant;
begin
  Result := 0;

  // Primary: nvidia-smi (reliable for NVIDIA GPUs, handles >4GB correctly).
  TmpFile := ExpandConstant('{tmp}\nvidiasmi.txt');
  if Exec('cmd.exe', '/c nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits > "' + TmpFile + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
  begin
    List := TStringList.Create;
    try
      if FileExists(TmpFile) then
      begin
        List.LoadFromFile(TmpFile);
        if List.Count > 0 then
        begin
          Line := Trim(List[0]);
          if TryStrToInt64(Line, Mb) and (Mb > 0) then
          begin
            Result := Integer(Mb);
            Exit;
          end;
        end;
      end;
    finally
      List.Free;
    end;
  end;

  // Fallback: WMI Win32_VideoController. AdapterRAM is a UInt32, so values
  // near/above 4GB overflow; only trust values that look sane.
  try
    Wmi := GetWMIObject('Win32_VideoController');
    Item := Wmi.AdapterRAM;
    if not VarIsNull(Item) then
    begin
      Mb := Int64(Item);
      // Overflowed uint32 (>4GB) produces a value > 0x7FFFFFFF or negative-ish.
      if (Mb > 0) and (Mb < $7FFFFFFF) then
        Result := Integer(Mb div (1024 * 1024));
    end;
  except
  end;
end;

function ShouldInstallOllama(): Boolean;
begin
  Result := OllamaCheckbox.Checked;
end;

procedure WarnLowVram();
var
  VramMb: Integer;
begin
  VramMb := GetTotalVramMb();
  if VramMb = 0 then
    Exit; // could not detect -> no warning
  if (VramMb > 0) and (VramMb < 6 * 1024) then
  begin
    MsgBox('Low VRAM warning' + #13#10 + #13#10 +
      'Your GPU has ' + IntToStr(VramMb div 1024) + ' GB of VRAM. The chat model ' +
      '(qwen3:4b) needs about 6 GB to run fast. LakituAI will still work, but ' +
      'chat responses may be slow.', mbInformation, MB_OK);
  end;
end;

function IsOllamaInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('ollama', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure InitializeWizard();
begin
  // VRAM warning (only once) right after the wizard is created.
  if not VramWarningShown then
  begin
    WarnLowVram();
    VramWarningShown := True;
  end;

  // Optional Ollama setup page.
  OllamaPage := CreateCustomPage(wpSelectTasks, 'Optional: Chat AI (Ollama)',
    'LakituAI can install the local chat model automatically.');
  OllamaCheckbox := TNewCheckBox.Create(OllamaPage);
  OllamaCheckbox.Parent := OllamaPage.Surface;
  OllamaCheckbox.Width := OllamaPage.SurfaceWidth;
  OllamaCheckbox.Caption := 'Install Ollama and download the qwen3:4b chat model';
  OllamaCheckbox.Checked := not IsOllamaInstalled();
end;

// ---------------------------------------------------------------------------
// Uninstaller: ask which optional data to remove, then delete it.
// ---------------------------------------------------------------------------

procedure InitializeUninstallProgressForm();
var
  Form: TSetupForm;
  ContinueButton, CancelButton: TNewButton;
  HeaderText: TNewStaticText;
begin
  // In silent mode (/VERYSILENT) there is no UI; skip the prompt and let
  // CurUninstallStepChanged remove everything by default.
  if UninstallSilent then
    Exit;

  Form := CreateCustomForm;
  Form.Caption := 'Remove LakituAI data';
  Form.ClientWidth := ScaleX(440);
  Form.ClientHeight := ScaleY(260);
  Form.Center;

  HeaderText := TNewStaticText.Create(Form);
  HeaderText.Parent := Form;
  HeaderText.Left := ScaleX(20);
  HeaderText.Top := ScaleY(16);
  HeaderText.Width := ScaleX(400);
  HeaderText.AutoSize := True;
  HeaderText.WordWrap := True;
  HeaderText.Caption := 'Select what to remove with LakituAI:';

  UninstallDataCheckbox := TNewCheckBox.Create(Form);
  UninstallDataCheckbox.Parent := Form;
  UninstallDataCheckbox.Left := ScaleX(20);
  UninstallDataCheckbox.Top := ScaleY(64);
  UninstallDataCheckbox.Width := ScaleX(400);
  UninstallDataCheckbox.Caption := 'Delete all LakituAI data (config, database, screenshots)';
  UninstallDataCheckbox.Checked := True;

  UninstallModelCheckbox := TNewCheckBox.Create(Form);
  UninstallModelCheckbox.Parent := Form;
  UninstallModelCheckbox.Left := ScaleX(20);
  UninstallModelCheckbox.Top := ScaleY(104);
  UninstallModelCheckbox.Width := ScaleX(400);
  UninstallModelCheckbox.Caption := 'Remove the qwen3:4b chat model from Ollama';
  UninstallModelCheckbox.Checked := True;

  CancelButton := TNewButton.Create(Form);
  CancelButton.Parent := Form;
  CancelButton.Caption := 'Cancel';
  CancelButton.Left := ScaleX(230);
  CancelButton.Top := Form.ClientHeight - ScaleY(50);
  CancelButton.Width := ScaleX(90);
  CancelButton.ModalResult := mrCancel;
  CancelButton.Cancel := True;

  ContinueButton := TNewButton.Create(Form);
  ContinueButton.Parent := Form;
  ContinueButton.Caption := 'Uninstall';
  ContinueButton.Left := CancelButton.Left + CancelButton.Width + ScaleX(8);
  ContinueButton.Top := CancelButton.Top;
  ContinueButton.Width := ScaleX(90);
  ContinueButton.ModalResult := mrOk;
  ContinueButton.Default := True;

  if Form.ShowModal <> mrOk then
    Abort;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Silent uninstall removes everything; interactive honors the checkbox state.
    if UninstallSilent or ((UninstallDataCheckbox <> nil) and UninstallDataCheckbox.Checked) then
      DelTree(ExpandConstant('{userappdata}\LakituAI'), True, True, True);

    // Remove the qwen3:4b chat model if requested (silent = always).
    if UninstallSilent or ((UninstallModelCheckbox <> nil) and UninstallModelCheckbox.Checked) then
      Exec('ollama', 'rm qwen3:4b', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;