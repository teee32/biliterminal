on run
    set bundlePath to POSIX path of (path to me)
    do shell script "open -a Terminal " & quoted form of (bundlePath & "Contents/Resources/launch.command")
end run
