/* Win64 inter-process acquire/release primitives for the SkyCraft protocol. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
__declspec(dllexport) uint32_t mc_load32(volatile LONG *p) { return (uint32_t)InterlockedCompareExchange(p, 0, 0); }
__declspec(dllexport) uint64_t mc_load64(volatile LONG64 *p) { return (uint64_t)InterlockedCompareExchange64(p, 0, 0); }
__declspec(dllexport) uint32_t mc_exchange32(volatile LONG *p, uint32_t v) { return (uint32_t)InterlockedExchange(p, (LONG)v); }
__declspec(dllexport) void mc_store64(volatile LONG64 *p, uint64_t v) { InterlockedExchange64(p, (LONG64)v); }

