#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <signal.h>

static volatile sig_atomic_t g_stop_requested = 0;
static volatile sig_atomic_t g_pause_requested = 0;
static volatile sig_atomic_t g_resume_requested = 0;

static void handle_signal(int signo) {
    if (signo == SIGTERM || signo == SIGINT) {
        g_stop_requested = 1;
    } else if (signo == SIGUSR1) {
        g_pause_requested = 1;
    } else if (signo == SIGUSR2) {
        g_resume_requested = 1;
    }
}

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        if (argc < 2) {
            fprintf(stderr, "usage: %s <audio-file>\n", argv[0]);
            return 2;
        }

        signal(SIGTERM, handle_signal);
        signal(SIGINT, handle_signal);
        signal(SIGUSR1, handle_signal);
        signal(SIGUSR2, handle_signal);

        NSString *path = [NSString stringWithUTF8String:argv[1]];
        NSURL *url = [NSURL fileURLWithPath:path];
        NSError *error = nil;
        AVAudioPlayer *player = [[AVAudioPlayer alloc] initWithContentsOfURL:url error:&error];
        if (player == nil) {
            fprintf(stderr, "%s\n", error.localizedDescription.UTF8String ?: "failed to open audio");
            return 1;
        }
        [player prepareToPlay];
        if (![player play]) {
            fprintf(stderr, "failed to play audio\n");
            return 1;
        }

        BOOL paused = NO;
        NSRunLoop *runLoop = [NSRunLoop currentRunLoop];
        while (!g_stop_requested && ([player isPlaying] || paused)) {
            if (g_pause_requested) {
                if ([player isPlaying]) {
                    [player pause];
                    paused = YES;
                }
                g_pause_requested = 0;
            }
            if (g_resume_requested) {
                if (paused) {
                    [player play];
                    paused = NO;
                }
                g_resume_requested = 0;
            }
            [runLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
            if (![player isPlaying] && !paused) {
                break;
            }
        }

        [player stop];
        return 0;
    }
}
