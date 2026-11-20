# A tiny window for the screen assist end-to-end test: a text box and a Save button
# that writes the box's text to -OutFile.
param([Parameter(Mandatory = $true)][string]$OutFile)
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.Text = "Nova Test Fixture"
$form.Width = 440
$form.Height = 200
$form.StartPosition = "CenterScreen"
$form.TopMost = $true
$box = New-Object System.Windows.Forms.TextBox
$box.Left = 20
$box.Top = 20
$box.Width = 380
$box.AccessibleName = "Message"
$button = New-Object System.Windows.Forms.Button
$button.Text = "Save"
$button.Left = 20
$button.Top = 70
$button.Width = 120
$question = New-Object System.Windows.Forms.Label
$question.Text = "Question 1: What is 6 times 7?"
$question.Left = 160
$question.Top = 74
$question.Width = 240
$form.Controls.Add($question)
$button.Add_Click({ Set-Content -LiteralPath $OutFile -Value $box.Text -NoNewline })
$form.Controls.Add($box)
$form.Controls.Add($button)
[void]$form.ShowDialog()
