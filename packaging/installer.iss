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
; Helper script to fully remove Ollama. Must live in {app} so the uninstaller
; can run it before Inno deletes the app directory.
Source: "installer\uninstall_ollama.ps1"; DestDir: "{app}"

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
  UninstallOllamaCheckbox: TNewCheckBox;
  OllamaProgressPage: TOutputProgressWizardPage;
  OllamaRunning: Boolean;
  OllamaLog, OllamaDone, OllamaErr: String;
  OllamaProgress, OllamaPidFile: String;
  OllamaTimerId: UINT_PTR;

function SetTimer(hWnd: HWND; nIDEvent: UINT_PTR; uElapse: UINT; lpTimerFunc: Longint): UINT_PTR;
  external 'SetTimer@user32.dll stdcall';

function KillTimer(hWnd: HWND; uIDEvent: UINT_PTR): BOOL;
  external 'KillTimer@user32.dll stdcall';

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
  OllamaCheckbox.Caption := 'Install Ollama (~1.5 GB) and download the qwen3:4b chat model (~2.5 GB)';
  // Default to installing only when there is enough VRAM (or VRAM is unknown)
  // and Ollama isn't already present.
  OllamaCheckbox.Checked := ((DetectedVramMb = 0) or (DetectedVramMb >= 6 * 1024)) and not IsOllamaInstalled();

  // Progress page shown while Ollama + the chat model are being set up.
  // Real percentage (not a marquee): the background script writes the overall
  // progress to a temp file that a timer polls while Exec waits.
  OllamaProgressPage := CreateOutputProgressPage('Installing Ollama',
    'Setting up Ollama and the qwen3:4b chat model. This may take several minutes.');
end;

procedure OllamaTimerProc(Arg1: Longint; Arg2: Longint; Arg3: Longint; Arg4: Longint); forward;

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
      OllamaProgress := ExpandConstant('{tmp}\ollama_progress.txt');
      OllamaPidFile := ExpandConstant('{tmp}\ollama_pid.txt');

      OllamaRunning := True;
      // Inno disables the wizard's Cancel button (and the title-bar close)
      // during the install steps; re-enable it so the user can abort the
      // Ollama setup, which is the only long-running part left.
      WizardForm.CancelButton.Enabled := True;
      OllamaProgressPage.SetProgress(0, 100);
      OllamaProgressPage.SetText('Starting...', '');
      OllamaProgressPage.Show;

      // Poll the script's progress file while it runs. Exec with
      // ewWaitUntilTerminated pumps messages, so the timer below keeps firing
      // even though this code is blocked on the PowerShell process.
      OllamaTimerId := SetTimer(WizardForm.Handle, 1, 500, CreateCallback(@OllamaTimerProc));

      Exec('powershell.exe',
        '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\install_ollama.ps1') +
        '" "' + OllamaLog + '" "' + OllamaDone + '" "' + OllamaErr + '" "' +
        OllamaProgress + '" "' + OllamaPidFile + '"',
        '', SW_HIDE, ewWaitUntilTerminated, Res);

      KillTimer(WizardForm.Handle, OllamaTimerId);
      OllamaRunning := False;
      OllamaProgressPage.Hide;

      if FileExists(OllamaErr) then
        MsgBox('Ollama setup did not complete. The application is installed but the ' +
          'chat model was not downloaded. You can install Ollama and qwen3:4b later.',
          mbError, MB_OK);
    end;
  end;
end;

function ReadOllamaProgress(const FileName: String; var Pct: Integer; var Phase: String): Boolean;
var
  Lines: TStringList;
  I: Integer;
  Line: String;
begin
  Result := False;
  Pct := -1;
  Phase := '';
  if not FileExists(FileName) then
    Exit;
  Lines := TStringList.Create;
  try
    Lines.LoadFromFile(FileName);
    for I := 0 to Lines.Count - 1 do
    begin
      Line := Trim(Lines[I]);
      if Pos('PCT|', Line) = 1 then
        Pct := StrToIntDef(Copy(Line, 5, MaxInt), -1)
      else if Pos('PHASE|', Line) = 1 then
        Phase := Copy(Line, 7, MaxInt);
    end;
    Result := Pct >= 0;
  finally
    Lines.Free;
  end;
end;

function ReadOllamaPid(const FileName: String): Integer;
var
  Lines: TStringList;
begin
  Result := -1;
  if not FileExists(FileName) then
    Exit;
  Lines := TStringList.Create;
  try
    Lines.LoadFromFile(FileName);
    if Lines.Count > 0 then
      Result := StrToIntDef(Trim(Lines[0]), -1);
  finally
    Lines.Free;
  end;
end;

procedure OllamaTimerProc(Arg1: Longint; Arg2: Longint; Arg3: Longint; Arg4: Longint);
var
  Pct: Integer;
  Phase: String;
begin
  try
    if ReadOllamaProgress(OllamaProgress, Pct, Phase) then
    begin
      OllamaProgressPage.SetProgress(Pct, 100);
      if Phase <> '' then
        OllamaProgressPage.SetText(Phase, '');
    end;
  except
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
var
  Res: Integer;
  Pid: Integer;
begin
  if OllamaRunning then
  begin
    // Kill the PowerShell process driving the download first (it wrote its
    // PID to a temp file at startup), then Ollama itself, then roll back.
    // Killing only ollama.exe did not help because the slow part is the
    // PowerShell process downloading the installer / streaming the model.
    Pid := ReadOllamaPid(OllamaPidFile);
    if Pid > 0 then
      Exec('taskkill', '/pid ' + IntToStr(Pid) + ' /f /t', '', SW_HIDE, ewWaitUntilTerminated, Res);
    Exec('taskkill', '/f /im ollama.exe', '', SW_HIDE, ewWaitUntilTerminated, Res);
    Exec('taskkill', '/f /im "ollama app.exe"', '', SW_HIDE, ewWaitUntilTerminated, Res);
    OllamaRunning := False;
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

  Form := CreateCustomForm(ScaleX(440), ScaleY(310), False, False);
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

  UninstallOllamaCheckbox := TNewCheckBox.Create(Form);
  UninstallOllamaCheckbox.Parent := Form;
  UninstallOllamaCheckbox.Left := ScaleX(20);
  UninstallOllamaCheckbox.Top := ScaleY(144);
  UninstallOllamaCheckbox.Width := ScaleX(400);
  UninstallOllamaCheckbox.Caption := 'Remove Ollama completely (program, service and models)';
  UninstallOllamaCheckbox.Checked := True;

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
  if CurUninstallStep = usUninstall then
  begin
    // Fully remove Ollama (program, service, data, models) when requested.
    // Runs here, before Inno deletes {app}, so the bundled script exists.
    if UninstallSilent or ((UninstallOllamaCheckbox <> nil) and UninstallOllamaCheckbox.Checked) then
      Exec('powershell.exe',
        '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\uninstall_ollama.ps1') + '"',
        '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    // Silent uninstall removes everything; interactive honors the checkbox state.
    if UninstallSilent or ((UninstallDataCheckbox <> nil) and UninstallDataCheckbox.Checked) then
      DelTree(ExpandConstant('{userappdata}\LakituAI'), True, True, True);

    // Remove the qwen3:4b chat model unless Ollama itself was removed above
    // (which already deletes all models).
    if (not (UninstallSilent or ((UninstallOllamaCheckbox <> nil) and UninstallOllamaCheckbox.Checked)))
       and (UninstallSilent or ((UninstallModelCheckbox <> nil) and UninstallModelCheckbox.Checked)) then
      Exec('ollama', 'rm qwen3:4b', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;