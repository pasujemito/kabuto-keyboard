#pragma once
// Minimal deterministic host adapter. No Bluetooth, scheduler or hardware is
// emulated; tests exercise the real interpreter against recorded HID calls.
#include <cstdint>
#include <cstddef>
#include <string>
#include <functional>
using String = std::string;
using TaskHandle_t = void*;
using QueueHandle_t = void*;
using TickType_t = uint32_t;
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)(x))
#define portEXIT_CRITICAL(x) ((void)(x))
#define pdMS_TO_TICKS(x) (x)
#define pdTRUE 1
#define pdPASS 1
extern uint32_t testClock;
extern std::function<void()> testDelayHook;
inline uint32_t millis() { return testClock; }
inline void vTaskDelay(uint32_t ticks) { testClock += ticks; if(testDelayHook) testDelayHook(); }
inline long random(long) { return 0; } // always lowest eligible weighted interval
inline long random(long low, long) { return low; }
inline QueueHandle_t xQueueCreate(int, std::size_t) { return nullptr; }
inline int xQueueSend(QueueHandle_t, const void*, int) { return 0; }
inline int xQueueReceive(QueueHandle_t, void*, int) { return 0; }
inline int xTaskCreatePinnedToCore(void (*)(void*), const char*, int, void*, int, TaskHandle_t*, int) { return 0; }
inline void vTaskDelete(TaskHandle_t) {}
