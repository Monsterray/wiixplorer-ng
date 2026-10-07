// macOS HDMI capture helper. No audio, listener, or permanent background process.
// clang -fobjc-arc -framework Foundation -framework AVFoundation -framework
// CoreImage -framework CoreMedia -framework AppKit scripts/wii-capture.m -o build/tools/wii-capture
#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreImage/CoreImage.h>
#import <AppKit/AppKit.h>

@interface Capture : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
@property NSString *directory;
@property CIContext *context;
@property NSDate *last;
@property unsigned frames;
@property BOOL failed;
@end
@implementation Capture
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
        if (argc != 4 || !getenv("WII_BENCH_JOB_START") || !getenv("WII_BENCH_IP")) {
            fprintf(stderr, "Usage inside Wii dev queue: wii-capture DEVICE_ID NEW_DIRECTORY SECONDS (1..600)\n"); return 2;
        }
        char *end = NULL; long seconds = strtol(argv[3], &end, 10);
        if (!end || *end || seconds < 1 || seconds > 600) return 2;
        AVCaptureDevice *selected = nil;
        for (AVCaptureDevice *device in devices) if ([device.uniqueID isEqualToString:@(argv[1])]) selected = device;
        if (!selected) { fprintf(stderr, "Capture device unavailable\n"); return 1; }
        // Fail instead of opening a privacy prompt in unattended queue jobs.
        // Authorize the stable helper once in macOS Camera settings if needed.
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
        Capture *capture = [Capture new]; capture.directory = directory; capture.context = [CIContext contextWithOptions:nil];
        dispatch_queue_t queue = dispatch_queue_create("wiixplorer.capture", DISPATCH_QUEUE_SERIAL);
        [output setSampleBufferDelegate:capture queue:queue];
        if (!input || ![session canAddInput:input] || ![session canAddOutput:output]) return 1;
        [session addInput:input]; [session addOutput:output]; [session startRunning];
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]];
        [session stopRunning]; [output setSampleBufferDelegate:nil queue:NULL];
        dispatch_sync(queue, ^{});
        printf("Captured %u frames from %s\n", capture.frames, selected.localizedName.UTF8String);
        return capture.frames && !capture.failed ? 0 : 1;
    }
}
