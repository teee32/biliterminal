on run
    set bundlePath to POSIX path of (path to me)
    set launchPath to quoted form of (bundlePath & "Contents/Resources/launch.command")
    do shell script "open -a Terminal.app " & launchPath
end run
