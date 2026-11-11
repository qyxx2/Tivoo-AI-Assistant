#include "network_listeners.h"

#include <errno.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#else
#include <pthread.h>
#include <time.h>
#endif

#define LISTENER_BACKLOG 2
#define SELECT_TIMEOUT_MS 100

typedef struct {
    uint16_t port;
    int listener_fd;
    int client_fd;
} listener_endpoint_t;

static listener_endpoint_t s_endpoints[2];
static atomic_bool s_running = ATOMIC_VAR_INIT(false);
static atomic_bool s_ip_available = ATOMIC_VAR_INIT(false);
static atomic_bool s_worker_running = ATOMIC_VAR_INIT(false);

#ifdef ESP_PLATFORM
static TaskHandle_t s_worker;
#else
static pthread_t s_worker;
static bool s_thread_started;
#endif

static void delay_one_tick(void)
{
#ifdef ESP_PLATFORM
    vTaskDelay(pdMS_TO_TICKS(SELECT_TIMEOUT_MS));
#else
    const struct timespec delay = {
        .tv_sec = 0,
        .tv_nsec = SELECT_TIMEOUT_MS * 1000000L,
    };
    nanosleep(&delay, NULL);
#endif
}

static void close_fd(int *fd)
{
    if (*fd >= 0) {
        close(*fd);
        *fd = -1;
    }
}

static void close_endpoint(listener_endpoint_t *endpoint)
{
    close_fd(&endpoint->client_fd);
    close_fd(&endpoint->listener_fd);
}

static int set_nonblocking(int fd)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) {
        return -1;
    }
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

static int create_listener(uint16_t port)
{
    int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (fd < 0) {
        return -1;
    }

    int reuse_address = 1;
    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse_address,
                     sizeof(reuse_address));

    const struct sockaddr_in address = {
        .sin_family = AF_INET,
        .sin_port = htons(port),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };

    if (bind(fd, (const struct sockaddr *)&address, sizeof(address)) < 0 ||
        listen(fd, LISTENER_BACKLOG) < 0 || set_nonblocking(fd) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static void accept_one_client(listener_endpoint_t *endpoint)
{
    int client_fd = accept(endpoint->listener_fd, NULL, NULL);
    if (client_fd < 0) {
        return;
    }

    if (endpoint->client_fd >= 0 || set_nonblocking(client_fd) < 0) {
        close(client_fd);
        return;
    }
    endpoint->client_fd = client_fd;
}

static void check_client(listener_endpoint_t *endpoint)
{
    char byte;
    int result = (int)recv(endpoint->client_fd, &byte, sizeof(byte), MSG_PEEK);
    if (result == 0 || result > 0 ||
        (result < 0 && errno != EAGAIN && errno != EWOULDBLOCK &&
         errno != EINTR)) {
        /* P5b1 has no payload protocol. Close clients that send early data. */
        close_fd(&endpoint->client_fd);
    }
}

static void poll_listeners(void)
{
    fd_set readable;
    FD_ZERO(&readable);
    int max_fd = -1;

    for (size_t i = 0; i < 2; i++) {
        listener_endpoint_t *endpoint = &s_endpoints[i];
        if (endpoint->listener_fd >= 0) {
            FD_SET(endpoint->listener_fd, &readable);
            if (endpoint->listener_fd > max_fd) {
                max_fd = endpoint->listener_fd;
            }
        }
        if (endpoint->client_fd >= 0) {
            FD_SET(endpoint->client_fd, &readable);
            if (endpoint->client_fd > max_fd) {
                max_fd = endpoint->client_fd;
            }
        }
    }

    if (max_fd < 0) {
        delay_one_tick();
        return;
    }

    struct timeval timeout = {
        .tv_sec = 0,
        .tv_usec = SELECT_TIMEOUT_MS * 1000,
    };
    int ready = select(max_fd + 1, &readable, NULL, NULL, &timeout);
    if (ready <= 0) {
        return;
    }

    for (size_t i = 0; i < 2; i++) {
        listener_endpoint_t *endpoint = &s_endpoints[i];
        if (endpoint->listener_fd >= 0 &&
            FD_ISSET(endpoint->listener_fd, &readable)) {
            accept_one_client(endpoint);
        }
        if (endpoint->client_fd >= 0 &&
            FD_ISSET(endpoint->client_fd, &readable)) {
            check_client(endpoint);
        }
    }
}

static void listener_worker(void)
{
    while (atomic_load(&s_running)) {
        if (!atomic_load(&s_ip_available)) {
            for (size_t i = 0; i < 2; i++) {
                close_endpoint(&s_endpoints[i]);
            }
            delay_one_tick();
            continue;
        }

        for (size_t i = 0; i < 2; i++) {
            if (s_endpoints[i].listener_fd < 0) {
                s_endpoints[i].listener_fd =
                    create_listener(s_endpoints[i].port);
            }
        }
        poll_listeners();
    }

    for (size_t i = 0; i < 2; i++) {
        close_endpoint(&s_endpoints[i]);
    }
    atomic_store(&s_worker_running, false);
}

#ifdef ESP_PLATFORM
static void listener_task(void *context)
{
    (void)context;
    listener_worker();
    s_worker = NULL;
    vTaskDelete(NULL);
}
#else
static void *listener_thread(void *context)
{
    (void)context;
    listener_worker();
    return NULL;
}
#endif

esp_err_t network_listeners_start(uint16_t control_port, uint16_t diagnostic_port)
{
    if (control_port == 0 || diagnostic_port == 0 ||
        control_port == diagnostic_port) {
        return ESP_FAIL;
    }

    bool expected = false;
    if (!atomic_compare_exchange_strong(&s_running, &expected, true)) {
        return ESP_ERR_INVALID_STATE;
    }

    s_endpoints[0] = (listener_endpoint_t){
        .port = control_port,
        .listener_fd = -1,
        .client_fd = -1,
    };
    s_endpoints[1] = (listener_endpoint_t){
        .port = diagnostic_port,
        .listener_fd = -1,
        .client_fd = -1,
    };
    atomic_store(&s_ip_available, false);
    atomic_store(&s_worker_running, true);

#ifdef ESP_PLATFORM
    if (xTaskCreate(listener_task, "tivoo_tcp", 4096, NULL, 5, &s_worker) !=
        pdPASS) {
        atomic_store(&s_running, false);
        atomic_store(&s_worker_running, false);
        return ESP_FAIL;
    }
#else
    if (pthread_create(&s_worker, NULL, listener_thread, NULL) != 0) {
        atomic_store(&s_running, false);
        atomic_store(&s_worker_running, false);
        return ESP_FAIL;
    }
    s_thread_started = true;
#endif
    return ESP_OK;
}

void network_listeners_set_ip_available(bool available)
{
    atomic_store(&s_ip_available, available);
}

void network_listeners_stop(void)
{
    atomic_store(&s_ip_available, false);
    atomic_store(&s_running, false);

#ifdef ESP_PLATFORM
    while (atomic_load(&s_worker_running)) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    s_worker = NULL;
#else
    if (s_thread_started) {
        pthread_join(s_worker, NULL);
        s_thread_started = false;
    }
#endif
}
