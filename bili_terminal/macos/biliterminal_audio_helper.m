#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreMedia/CoreMedia.h>
#import <signal.h>
#import <unistd.h>

// 用法:
//   biliterminal-audio-helper <audio-file>
//   biliterminal-audio-helper --stream <url> <referer> <user-agent> [mime] [cookie-file]
//
// 信号协议: SIGUSR1 暂停, SIGUSR2 继续, SIGTERM/SIGINT 停止。
// 暂停走 AVPlayer/AVAudioPlayer 原生 pause，不会留下未消费的
// CoreAudio 缓冲，避免 SIGSTOP 挂起播放器时出现的重复卡顿声。

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

static void install_signal_handlers(void) {
    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    signal(SIGUSR1, handle_signal);
    signal(SIGUSR2, handle_signal);
}

static NSString *read_cookie_file(NSString *path) {
    if (path.length == 0) {
        return @"";
    }
    NSError *error = nil;
    NSString *cookie = [NSString stringWithContentsOfFile:path
                                                  encoding:NSUTF8StringEncoding
                                                     error:&error];
    unlink(path.fileSystemRepresentation);
    if (cookie == nil) {
        return @"";
    }
    return [cookie stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
}

static int run_stream_mode(NSString *urlString, NSString *referer, NSString *userAgent, NSString *mimeType, NSString *cookieFile) {
    NSURL *url = [NSURL URLWithString:urlString];
    if (url == nil) {
        fprintf(stderr, "invalid stream url\n");
        return 2;
    }
    NSMutableDictionary *options = [NSMutableDictionary dictionary];
    NSMutableDictionary *headers = [NSMutableDictionary dictionary];
    if (referer.length > 0) {
        headers[@"Referer"] = referer;
    }
    if (userAgent.length > 0) {
        headers[@"User-Agent"] = userAgent;
    }
    NSString *cookie = read_cookie_file(cookieFile);
    if (cookie.length > 0) {
        headers[@"Cookie"] = cookie;
    }
    if (headers.count > 0) {
        options[@"AVURLAssetHTTPHeaderFieldsKey"] = headers;
    }
    if (mimeType.length > 0) {
        // B 站 CDN 给 .m4s 返回 text/plain，必须显式覆盖 MIME 才能解码
        options[@"AVURLAssetOverrideMIMETypeKey"] = mimeType;
    }

    AVURLAsset *asset = [AVURLAsset URLAssetWithURL:url options:options];
    AVPlayerItem *item = [AVPlayerItem playerItemWithAsset:asset];
    AVPlayer *player = [AVPlayer playerWithPlayerItem:item];
    player.actionAtItemEnd = AVPlayerActionAtItemEndPause;

    __block BOOL finished = NO;
    id observer = [[NSNotificationCenter defaultCenter]
        addObserverForName:AVPlayerItemDidPlayToEndTimeNotification
                    object:item
                     queue:[NSOperationQueue mainQueue]
                usingBlock:^(NSNotification *note) {
                    (void)note;
                    finished = YES;
                }];

    [player play];

    BOOL paused = NO;
    NSDate *startedAt = [NSDate date];
    NSRunLoop *runLoop = [NSRunLoop currentRunLoop];
    int exitCode = 0;
    while (!g_stop_requested && !finished) {
        if (g_pause_requested) {
            g_pause_requested = 0;
            if (!paused) {
                [player pause];
                paused = YES;
            }
        }
        if (g_resume_requested) {
            g_resume_requested = 0;
            if (paused) {
                [player play];
                paused = NO;
            }
        }
        if (item.status == AVPlayerItemStatusFailed) {
            fprintf(stderr, "stream failed: %s\n",
                    item.error.localizedDescription.UTF8String ?: "unknown error");
            exitCode = 1;
            break;
        }
        if (!paused && item.status == AVPlayerItemStatusReadyToPlay) {
            CMTime duration = item.duration;
            CMTime current = player.currentTime;
            if (CMTIME_IS_NUMERIC(duration) && CMTIME_IS_NUMERIC(current) &&
                CMTimeGetSeconds(duration) > 0 &&
                CMTimeGetSeconds(current) >= CMTimeGetSeconds(duration) - 0.1) {
                break;
            }
        }
        // 起播 20 秒后仍未就绪，视为流打开失败
        if (item.status == AVPlayerItemStatusUnknown &&
            [[NSDate date] timeIntervalSinceDate:startedAt] > 20.0) {
            fprintf(stderr, "stream open timeout\n");
            exitCode = 1;
            break;
        }
        [runLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    }

    [[NSNotificationCenter defaultCenter] removeObserver:observer];
    [player pause];
    return exitCode;
}

static int run_file_mode(NSString *path) {
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

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        if (argc < 2) {
            fprintf(stderr, "usage: %s <audio-file>\n       %s --stream <url> <referer> <user-agent> [mime] [cookie-file]\n",
                    argv[0], argv[0]);
            return 2;
        }

        install_signal_handlers();

        if (strcmp(argv[1], "--stream") == 0) {
            if (argc < 5) {
                fprintf(stderr, "usage: %s --stream <url> <referer> <user-agent> [mime] [cookie-file]\n", argv[0]);
                return 2;
            }
            NSString *url = [NSString stringWithUTF8String:argv[2]];
            NSString *referer = [NSString stringWithUTF8String:argv[3]];
            NSString *userAgent = [NSString stringWithUTF8String:argv[4]];
            NSString *mime = argc >= 6 ? [NSString stringWithUTF8String:argv[5]] : @"";
            NSString *cookieFile = argc >= 7 ? [NSString stringWithUTF8String:argv[6]] : @"";
            return run_stream_mode(url, referer, userAgent, mime, cookieFile);
        }

        NSString *path = [NSString stringWithUTF8String:argv[1]];
        return run_file_mode(path);
    }
}
