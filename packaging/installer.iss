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
OutputDir=..\installer-output
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

[Code]
var
  OllamaPage: TWizardPage;
  OllamaCheckbox: TNewCheckBox;
  DetectedVramMb: Integer;
  UninstallDataCheckbox: TNewCheckBox;
  UninstallModelCheckbox: TNewCheckBox;
  OllamaProgressPage: TOutputProgressPage;
  OllamaTimer: TTimer;
  OllamaRunning: Boolean;
  OllamaLog, OllamaDone, OllamaErr: String;

function QueryVideoControllerVramMb(): Integer;
var
  Wmi, WbemObjectSet, WbemObject: Variant;
  I: Integer;
  Raw: Int64;
begin
  Result := 0;
  try
    Wmi := CreateOleObject('WbemScripting.SWbemLocator');
    WbemObjectSet := Wmi.ConnectServer('', 'root\cimv2').ExecQuery('SELECT AdapterRAM FROM Win32_VideoController');
    for I := 0 to WbemObjectSet.Count - 1 do
    begin
      WbemObject := WbemObjectSet.ItemIndex(I);
      if not VarIsNull(WbemObject.AdapterRAM) then
      begin
        Raw := Int64(WbemObject.AdapterRAM);
        // AdapterRAM is a UInt32; values >= 4 GB overflow into negative/garbage,
        // so only trust values that look sane.
        if (Raw > 0) and (Raw < $7FFFFFFF) then
        begin
          Result := Integer(Raw div (1024 * 1024));
          Break;
        end;
      end;
    end;
  except
  end;
end;

function GetTotalVramMb(): Integer;
var
  TmpFile, Line: String;
  ResultCode: Integer;
  List: TStringList;
  V: Integer;
begin
  Result := 0;

  // Primary: nvidia-smi (reliable for NVIDIA GPUs; reports real total in MB
  // even above 4 GB, unlike the overflowing WMI AdapterRAM field).
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
          V := StrToIntDef(Line, 0);
          if V > 0 then
            Result := V;
        end;
      end;
    finally
      List.Free;
    end;
  end;

  // Fallback: WMI Win32_VideoController (covers non-NVIDIA GPUs).
  if Result = 0 then
    Result := QueryVideoControllerVramMb();
end;

function ShouldInstallOllama(): Boolean;
begin
  Result := OllamaCheckbox.Checked;
end;

function IsOllamaInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('ollama', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure InitializeWizard();
begin
  // Detect VRAM once; warn if it's likely too low for the local chat model.
  DetectedVramMb := GetTotalVramMb();
  if (DetectedVramMb > 0) and (DetectedVramMb < 6 * 1024) then
  begin
    MsgBox('Low VRAM warning' + #13#10 + #13#10 +
      'Your GPU has about ' + IntToStr(DetectedVramMb div 1024) + ' GB of VRAM, but ' +
      'the local chat model (qwen3:4b) needs ~6 GB to run well. It is not ' +
      'recommended to install Ollama on this machine: chat responses will be very ' +
      'slow or may fail. You can skip the Ollama option on the next page.',
      mbInformation, MB_OK);
  end;

  // Optional Ollama setup page.
  OllamaPage := CreateCustomPage(wpSelectTasks, 'Optional: Chat AI (Ollama)',
    'LakituAI can install the local chat model automatically.');
  OllamaCheckbox := TNewCheckBox.Create(OllamaPage);
  OllamaCheckbox.Parent := OllamaPage.Surface;
  OllamaCheckbox.Width := OllamaPage.SurfaceWidth;
  OllamaCheckbox.Caption := 'Install Ollama and download the qwen3:4b chat model';
  // Default to installing only when there is enough VRAM (or VRAM is unknown)
  // and Ollama isn't already present.
  OllamaCheckbox.Checked := ((DetectedVramMb = 0) or (DetectedVramMb >= 6 * 1024)) and not IsOllamaInstalled();

  // Progress page shown while Ollama + the chat model are being set up.
  OllamaProgressPage := CreateOutputProgressPage('Installing Ollama',
    'Setting up Ollama and the qwen3:4b chat model. This may take several minutes.');
end;

function GetLastLogLine(const Path: String): String;
var
  List: TStringList;
  i: Integer;
  s: String;
begin
  Result := '';
  if not FileExists(Path) then
    Exit;
  List := TStringList.Create;
  try
    List.LoadFromFile(Path);
    for i := List.Count - 1 downto 0 do
    begin
      s := Trim(StringReplace(List[i], #13, '', [rfReplaceAll]));
      s := Trim(StringReplace(s, #10, '', [rfReplaceAll]));
      if s <> '' then
      begin
        Result := s;
        Exit;
      end;
    end;
  finally
    List.Free;
  end;
end;

procedure OllamaTimerTick(Sender: TObject);
var
  Res: Integer;
begin
  if not OllamaRunning then
    Exit;

  if FileExists(OllamaErr) then
  begin
    OllamaRunning := False;
    OllamaTimer.Enabled := False;
    OllamaProgressPage.Hide;
    MsgBox('Ollama setup did not complete. The application is installed but the ' +
      'chat model was not downloaded. You can install Ollama and qwen3:4b later.',
      mbError, MB_OK);
    Exit;
  end;

  if FileExists(OllamaDone) then
  begin
    OllamaRunning := False;
    OllamaTimer.Enabled := False;
    OllamaProgressPage.Hide;
    Exit;
  end;

  OllamaProgressPage.StatusLabel.Caption := GetLastLogLine(OllamaLog);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Res: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if ShouldInstallOllama() then
    begin
      OllamaLog := ExpandConstant('{tmp}\ollama_setup.log');
      OllamaDone := ExpandConstant('{tmp}\ollama_done.ok');
      OllamaErr := ExpandConstant('{tmp}\ollama_error.err');

      OllamaRunning := True;
      OllamaProgressPage.Show;
      OllamaProgressPage.StatusLabel.Caption := 'Preparing Ollama...';
      OllamaProgressPage.ProgressBar.Style := npbstMarquee;

      Exec('powershell.exe',
        '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\install_ollama.ps1') +
        '" "' + OllamaLog + '" "' + OllamaDone + '" "' + OllamaErr + '"',
        '', SW_HIDE, ewNoWait, Res);

      OllamaTimer := TTimer.Create(nil);
      OllamaTimer.Interval := 500;
      OllamaTimer.OnTimer := @OllamaTimerTick;
      OllamaTimer.Enabled := True;
    end;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
var
  Res: Integer;
begin
  if OllamaRunning then
  begin
    // Stop the download and remove any partially pulled model.
    Exec('taskkill', '/f /im ollama.exe', '', SW_HIDE, ewWaitUntilTerminated, Res);
    Exec('ollama', 'rm qwen3:4b', '', SW_HIDE, ewWaitUntilTerminated, Res);
    OllamaRunning := False;
    if OllamaTimer <> nil then
      OllamaTimer.Enabled := False;
    OllamaProgressPage.Hide;
    // Roll back the application installation.
    Cancel := True;
    Confirm := False;
  end;
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

  Form := CreateCustomForm(ScaleX(440), ScaleY(260), False, False);
  Form.Caption := 'Remove LakituAI data';
  Form.CenterOnShow := True;

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