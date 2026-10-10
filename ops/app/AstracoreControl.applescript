-- Astracore Control: one window to run Astracore (local test or production).
-- Built into "Astracore Control.app" by ops/app/build.sh. It drives ./astracore in the repo.

property repoFallback : "__REPO__"
property localURL : "http://localhost:8765"
property prodURL : "https://astracore.hoppyhome.nl"

on repoPath()
	-- The app normally sits in the repo root; if it was moved elsewhere, use the path it was built from.
	set appPath to POSIX path of (path to me)
	set parentDir to do shell script "dirname " & quoted form of appPath
	set here to do shell script "test -x " & quoted form of (parentDir & "/astracore") & " && echo yes || echo no"
	if here is "yes" then return parentDir
	return repoFallback
end repoPath

on astracore(args)
	try
		return do shell script "cd " & quoted form of repoPath() & " && ./astracore " & args & " 2>&1"
	on error errMsg
		return errMsg
	end try
end astracore

on isRunning()
	return (astracore("status") contains "App:    running")
end isRunning

on runningMode()
	set s to astracore("status")
	if s contains "production mode" then return "production"
	if s contains "local mode" then return "local"
	return ""
end runningMode

on startMode(modeName)
	if modeName is "production" then
		set ok to button returned of (display dialog "Put Astracore online at " & prodURL & "?" & return & return & ¬
			"Anyone on the invite list can log in while it runs." buttons {"Cancel", "Start production"} ¬
			default button "Start production" with title "Astracore" with icon caution)
		set out to astracore("start --prod")
		set siteURL to prodURL
	else
		set out to astracore("start")
		set siteURL to localURL
	end if
	if out contains "Astracore is up" then
		set b to button returned of (display dialog out buttons {"OK", "Open site"} default button "Open site" with title "Astracore")
		if b is "Open site" then open location siteURL
	else
		display dialog out buttons {"OK"} default button "OK" with title "Astracore" with icon stop
	end if
end startMode

on showLogs()
	tell application "Terminal"
		activate
		do script "cd " & quoted form of repoPath() & " && ./astracore logs"
	end tell
end showLogs

on run
	repeat
		set statusText to astracore("status")
		set curMode to runningMode()
		if curMode is "" then
			set choices to {"Start local test", "Start production", "Show logs"}
			set dflt to "Start local test"
		else
			set choices to {"Stop", "Open site", "Restart", "Show logs"}
			set dflt to "Open site"
		end if
		set pick to choose from list choices with title "Astracore" with prompt statusText default items {dflt} ¬
			OK button name "Go" cancel button name "Close"
		if pick is false then exit repeat
		set chosen to item 1 of pick
		try
			if chosen is "Start local test" then
				startMode("local")
			else if chosen is "Start production" then
				startMode("production")
			else if chosen is "Stop" then
				display dialog astracore("stop") buttons {"OK"} default button "OK" with title "Astracore"
			else if chosen is "Restart" then
				astracore("stop")
				startMode(curMode)
			else if chosen is "Open site" then
				if curMode is "production" then
					open location prodURL
				else
					open location localURL
				end if
				exit repeat
			else if chosen is "Show logs" then
				showLogs()
				exit repeat
			end if
		on error number -128
			-- Cancel in a dialog: back to the menu
		end try
	end repeat
end run
