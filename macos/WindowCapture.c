#include "WindowCapture.h"
#include <unistd.h>

/* Developer-only capture. Refuse every window not owned by this process. */
CGImageRef KBCreateOwnWindowImage(uint32_t windowID) {
    CFArrayRef records = CGWindowListCopyWindowInfo(kCGWindowListOptionIncludingWindow, windowID);
    if (!records || CFArrayGetCount(records) != 1) {
        if (records) CFRelease(records);
        return NULL;
    }
    CFDictionaryRef record = (CFDictionaryRef)CFArrayGetValueAtIndex(records, 0);
    CFNumberRef pidValue = (CFNumberRef)CFDictionaryGetValue(record, kCGWindowOwnerPID);
    int owner = -1;
    if (pidValue) CFNumberGetValue(pidValue, kCFNumberIntType, &owner);
    CFRelease(records);
    if (owner != getpid()) return NULL;
    return CGWindowListCreateImage(CGRectNull, kCGWindowListOptionIncludingWindow,
                                  windowID, kCGWindowImageBoundsIgnoreFraming);
}
