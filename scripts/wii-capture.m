// macOS HDMI capture helper. No audio, listener, or permanent background process.
// Build/sign with python3 scripts/build-wii-capture.py.
// Only explicit --authorize requests permission; queued recording never does.
#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreImage/CoreImage.h>
#import <AppKit/AppKit.h>
#include <signal.h>
static volatile sig_atomic_t stopping=0;
static void StopCapture(int signal) { (void)signal;stopping=1; }

@interface Capture : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate, AVCaptureFileOutputRecordingDelegate>
@property NSString *directory;
@property CIContext *context;
@property NSDate *last;
@property unsigned frames;
@property BOOL failed;
@property BOOL recordingFinished;
@end
@implementation Capture
- (void)captureOutput:(AVCaptureFileOutput *)output didFinishRecordingToOutputFileAtURL:(NSURL *)url fromConnections:(NSArray *)connections error:(NSError *)error {
    // AVFoundation can report a duration/size limit as a successfully saved file.
    BOOL saved = !error || [error.userInfo[AVErrorRecordingSuccessfullyFinishedKey] boolValue];
    if (!saved) { self.failed=YES;fprintf(stderr,"Video recording failed: %s\n",error.localizedDescription.UTF8String); }
    self.recordingFinished=YES;
}
- (void)captureOutput:(AVCaptureOutput *)output didOutputSampleBuffer:(CMSampleBufferRef)sample fromConnection:(AVCaptureConnection *)connection {
    @autoreleasepool {
        if (self.last && -self.last.timeIntervalSinceNow < 1) return;
        self.last = [NSDate date];
        CVImageBufferRef buffer = CMSampleBufferGetImageBuffer(sample);
        if (!buffer) { self.failed = YES; return; }
        CIImage *image = [CIImage imageWithCVPixelBuffer:buffer];
        CGImageRef bitmap = [self.context createCGImage:image fromRect:image.extent];
        if (!bitmap) { self.failed = YES; return; }
        NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithCGImage:bitmap];
        CGImageRelease(bitmap);
        NSData *jpeg = [rep representationUsingType:NSBitmapImageFileTypeJPEG properties:@{NSImageCompressionFactor:@0.85}];
        NSString *path = [self.directory stringByAppendingPathComponent:[NSString stringWithFormat:@"frame-%06u.jpg", self.frames]];
        if (!jpeg || ![jpeg writeToFile:path options:NSDataWritingAtomic error:nil]) self.failed = YES;
        else ++self.frames;
    }
}
@end

int main(int argc, const char **argv) {
    @autoreleasepool {
        NSArray<AVCaptureDevice *> *devices = [AVCaptureDevice devicesWithMediaType:AVMediaTypeVideo];
        if (argc == 2 && !strcmp(argv[1], "--list")) {
            fprintf(stderr,"Camera authorization: %ld (3 = authorized)\n",(long)[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo]);
            for (AVCaptureDevice *device in devices) printf("%s\t%s\n", device.uniqueID.UTF8String, device.localizedName.UTF8String);
            return 0;
        }
        if (argc==2 && !strcmp(argv[1],"--authorize")) {
            __block BOOL answered=NO,granted=NO;
            [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL allowed) { dispatch_async(dispatch_get_main_queue(), ^{ granted=allowed;answered=YES; }); }];
            NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:60];
            while(!answered && deadline.timeIntervalSinceNow>0) [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
            fprintf(stderr,"Camera authorization: %s\n",answered && granted ? "authorized" : "unavailable or denied");
            return answered && granted ? 0 : 1;
        }
        if (argc != 4 || !getenv("WII_BENCH_JOB_START") || !getenv("WII_BENCH_IP")) {
            fprintf(stderr, "Usage inside Wii dev queue: wii-capture DEVICE_ID NEW_DIRECTORY SECONDS (1..600)\n"); return 2;
        }
        char *end = NULL; long seconds = strtol(argv[3], &end, 10);
        if (!end || *end || seconds < 1 || seconds > 600) return 2;
        AVCaptureDevice *selected = nil;
        for (AVCaptureDevice *device in devices) if ([device.uniqueID isEqualToString:@(argv[1])]) selected = device;
        if (!selected) { fprintf(stderr, "Capture device unavailable\n"); return 1; }
        // Fail instead of opening a privacy prompt in unattended queue jobs.
        // The explicit --authorize command is the only mode that requests access.
        if ([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo] != AVAuthorizationStatusAuthorized) {
            fprintf(stderr, "Camera permission required for the HDMI capture helper\n"); return 1;
        }
        NSString *directory = @(argv[2]);
        if ([[NSFileManager defaultManager] fileExistsAtPath:directory] || ![[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:NO attributes:nil error:nil]) return 1;
        NSError *error = nil;
        AVCaptureDeviceInput *input = [AVCaptureDeviceInput deviceInputWithDevice:selected error:&error];
        AVCaptureSession *session = [AVCaptureSession new];
        AVCaptureVideoDataOutput *output = [AVCaptureVideoDataOutput new];
        output.alwaysDiscardsLateVideoFrames = YES;
        AVCaptureMovieFileOutput *movie=[AVCaptureMovieFileOutput new];
        movie.maxRecordedDuration=CMTimeMake(seconds,1);
        movie.maxRecordedFileSize=512LL*1024*1024; // Explicit disk-use bound per leased run.
        Capture *capture = [Capture new]; capture.directory = directory; capture.context = [CIContext contextWithOptions:nil];
        dispatch_queue_t queue = dispatch_queue_create("wiixplorer.capture", DISPATCH_QUEUE_SERIAL);
        [output setSampleBufferDelegate:capture queue:queue];
        if (!input || ![session canAddInput:input] || ![session canAddOutput:output] || ![session canAddOutput:movie]) return 1;
        [session addInput:input]; [session addOutput:output]; [session addOutput:movie];
        signal(SIGTERM,StopCapture);signal(SIGINT,StopCapture);
        [session startRunning];
        [movie startRecordingToOutputFileURL:[NSURL fileURLWithPath:[directory stringByAppendingPathComponent:@"video.mov"]] recordingDelegate:capture];
        NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:seconds];
        while(!stopping && !capture.recordingFinished && deadline.timeIntervalSinceNow>0)
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        [movie stopRecording];
        deadline=[NSDate dateWithTimeIntervalSinceNow:5];
        while(!capture.recordingFinished && deadline.timeIntervalSinceNow>0)
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        [session stopRunning]; [output setSampleBufferDelegate:nil queue:NULL];
        dispatch_sync(queue, ^{});
        printf("Captured %u frames from %s\n", capture.frames, selected.localizedName.UTF8String);
        return capture.frames && capture.recordingFinished && !capture.failed ? 0 : 1;
    }
}
