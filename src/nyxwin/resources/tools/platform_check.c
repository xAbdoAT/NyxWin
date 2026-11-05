#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

typedef uint32_t dyld_platform_t;

typedef struct {
    dyld_platform_t platform;
    uint32_t version;
} dyld_build_version_t;

/*
 * Dynamic Darwin Platform & OS Version Check Helper
 *
 * Implements compiler-rt builtins required by Swift & Clang availability checks:
 * - __isPlatformVersionAtLeast
 * - __isOSVersionAtLeast
 *
 * Calls dyld's `_availability_version_check` (available on iOS 13+) and falls back
 * to `sysctlbyname("kern.osproductversion")`.
 *
 * CRITICAL: Returning 1 unconditionally causes `#available(...)` to return true for
 * newer APIs (e.g. iOS 17.5+ lazy WindowGroup init on iOS 17.0), causing dyld weak symbol
 * resolution to NULL (0x0) and an immediate EXC_BAD_ACCESS (SIGSEGV) crash at launch!
 */

extern bool _availability_version_check(uint32_t count, const dyld_build_version_t versions[]) __attribute__((weak_import));
extern int sysctlbyname(const char *name, void *oldp, size_t *oldlenp, void *newp, size_t newlen);

int32_t __isPlatformVersionAtLeast(uint32_t Platform, uint32_t Major, uint32_t Minor, uint32_t Subminor) {
    if (_availability_version_check != NULL) {
        dyld_build_version_t req;
        req.platform = Platform;
        req.version = (Major << 16) | (Minor << 8) | Subminor;
        return _availability_version_check(1, &req) ? 1 : 0;
    }

    char os_ver[64] = {0};
    size_t len = sizeof(os_ver) - 1;
    if (sysctlbyname("kern.osproductversion", os_ver, &len, NULL, 0) == 0) {
        uint32_t cur_major = 0, cur_minor = 0, cur_subminor = 0;
        char *dot1 = strchr(os_ver, '.');
        if (dot1) {
            *dot1 = '\0';
            cur_major = (uint32_t)atoi(os_ver);
            char *dot2 = strchr(dot1 + 1, '.');
            if (dot2) {
                *dot2 = '\0';
                cur_minor = (uint32_t)atoi(dot1 + 1);
                cur_subminor = (uint32_t)atoi(dot2 + 1);
            } else {
                cur_minor = (uint32_t)atoi(dot1 + 1);
            }
        } else {
            cur_major = (uint32_t)atoi(os_ver);
        }

        if (cur_major > Major) return 1;
        if (cur_major < Major) return 0;
        if (cur_minor > Minor) return 1;
        if (cur_minor < Minor) return 0;
        return (cur_subminor >= Subminor) ? 1 : 0;
    }
    return 0;
}

int32_t __isOSVersionAtLeast(uint32_t Major, uint32_t Minor, uint32_t Subminor) {
    return __isPlatformVersionAtLeast(2 /* PLATFORM_IOS */, Major, Minor, Subminor);
}
