/* Deterministic host driver for the real UART/SPP workers. No RF simulation. */
#pragma once
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>

typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM -2
#define ESP_ERR_INVALID_STATE -3
static inline const char *esp_err_to_name(int e) {(void)e;return "fake";}
typedef enum {ESP_LOG_NONE,ESP_LOG_ERROR,ESP_LOG_WARN,ESP_LOG_INFO,ESP_LOG_DEBUG,ESP_LOG_VERBOSE} esp_log_level_t;
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
static inline void *heap_caps_malloc(size_t n,int caps) {(void)caps;return malloc(n);}
static inline void *heap_caps_calloc(size_t n,size_t z,int caps) {(void)caps;return calloc(n,z);}
#define heap_caps_free free

typedef int BaseType_t;
typedef uint32_t TickType_t;
typedef uint32_t EventBits_t;
typedef int portMUX_TYPE;
typedef void *TaskHandle_t;
typedef void *SemaphoreHandle_t;
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define portMAX_DELAY UINT32_MAX
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) ((void)(p))
#define portEXIT_CRITICAL(p) ((void)(p))
#define pdMS_TO_TICKS(t) (t)
#define configMAX_PRIORITIES 25
#define BIT0 (1u<<0)
#define BIT1 (1u<<1)
#define BIT2 (1u<<2)
#define BIT3 (1u<<3)
#define BIT4 (1u<<4)
#define BIT5 (1u<<5)
#define BIT6 (1u<<6)
#define BIT7 (1u<<7)
#define BIT8 (1u<<8)
#define BIT9 (1u<<9)
#define BIT10 (1u<<10)
#define BIT11 (1u<<11)
static TickType_t fake_now;
static inline TickType_t xTaskGetTickCount(void) {return fake_now;}
static inline int64_t esp_timer_get_time(void) {return (int64_t)fake_now*1000;}
static inline void vTaskDelay(TickType_t n) {fake_now+=n;}
static inline BaseType_t xTaskCreate(void (*f)(void *),const char *name,unsigned stack,void *arg,unsigned priority,TaskHandle_t *out) {
    (void)f;(void)name;(void)stack;(void)arg;(void)priority;if(out)*out=(void*)1;return pdPASS;
}
static inline void vTaskDelete(TaskHandle_t h) {(void)h;}
static inline void xTaskNotifyGive(TaskHandle_t h) {(void)h;}
static inline uint32_t ulTaskNotifyTake(int a,TickType_t b) {(void)a;(void)b;return 0;}
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void) {return (void*)1;}
static inline void xSemaphoreTake(SemaphoreHandle_t h,TickType_t t) {(void)h;(void)t;}
static inline void xSemaphoreGive(SemaphoreHandle_t h) {(void)h;}
static inline void vSemaphoreDelete(SemaphoreHandle_t h) {(void)h;}
typedef struct {size_t cap,size,head,count; unsigned char data[];} *QueueHandle_t;
static jmp_buf worker_exit;
static int worker_budget=-1;
static inline QueueHandle_t xQueueCreate(size_t cap,size_t size) {
    QueueHandle_t q=calloc(1,sizeof(*q)+cap*size);assert(q);q->cap=cap;q->size=size;return q;
}
static inline void xQueueReset(QueueHandle_t q) {q->head=q->count=0;}
#define vQueueDelete free
static inline size_t uxQueueMessagesWaiting(QueueHandle_t q) {return q->count;}
static inline BaseType_t xQueueSend(QueueHandle_t q,const void *p,TickType_t ticks) {
    (void)ticks;if(q->count==q->cap)return pdFALSE;
    memcpy(q->data+((q->head+q->count)%q->cap)*q->size,p,q->size);q->count++;return pdTRUE;
}
static inline BaseType_t xQueueReceive(QueueHandle_t q,void *p,TickType_t ticks) {
    if(worker_budget>=0 && worker_budget--==0)longjmp(worker_exit,1);
    if(!q->count){fake_now+=ticks;return pdFALSE;}
    memcpy(p,q->data+q->head*q->size,q->size);q->head=(q->head+1)%q->cap;q->count--;return pdTRUE;
}
typedef EventBits_t *EventGroupHandle_t;
static inline EventGroupHandle_t xEventGroupCreate(void) {return calloc(1,sizeof(EventBits_t));}
static inline EventBits_t xEventGroupGetBits(EventGroupHandle_t g) {return *g;}
static inline EventBits_t xEventGroupSetBits(EventGroupHandle_t g,EventBits_t bits) {return *g|=bits;}
static inline EventBits_t xEventGroupClearBits(EventGroupHandle_t g,EventBits_t bits) {EventBits_t old=*g;*g&=~bits;return old;}
static inline EventBits_t xEventGroupWaitBits(EventGroupHandle_t g,EventBits_t mask,int clear,int all,TickType_t ticks) {
    EventBits_t old=*g;if(all?(old&mask)==mask:(old&mask)!=0){if(clear)*g&=~mask;}else fake_now+=ticks;return old;
}
static inline void esp_fill_random(void *p,size_t n) {memset(p,0x42,n);}
enum {UART_NUM_1,UART_DATA_8_BITS,UART_PARITY_DISABLE,UART_STOP_BITS_1,UART_HW_FLOWCTRL_DISABLE,UART_SCLK_DEFAULT,UART_PIN_NO_CHANGE,UART_FIFO_OVF,UART_BUFFER_FULL};
typedef struct {int baud_rate,data_bits,parity,stop_bits,flow_ctrl,source_clk;} uart_config_t;
typedef struct {int type;} uart_event_t;
static inline int uart_param_config(int p,const uart_config_t *c) {(void)p;(void)c;return 0;}
static inline int uart_set_pin(int p,int a,int b,int c,int d) {(void)p;(void)a;(void)b;(void)c;(void)d;return 0;}
static inline int uart_driver_install(int p,int rx,int tx,int cap,QueueHandle_t *q,int flags) {(void)p;(void)rx;(void)tx;(void)flags;*q=xQueueCreate(cap,sizeof(uart_event_t));return 0;}
static inline void uart_driver_delete(int p) {(void)p;}
static inline void uart_flush_input(int p) {(void)p;}
static inline int uart_read_bytes(int p,void *b,size_t n,TickType_t t) {(void)p;(void)b;(void)n;(void)t;return 0;}
static inline int uart_write_bytes(int p,const void *b,size_t n) {(void)p;(void)b;return (int)n;}

typedef uint8_t esp_bd_addr_t[6];
typedef uint8_t esp_bt_pin_code_t[16];
typedef uint8_t esp_bt_io_cap_t;
typedef int esp_bt_gap_cb_event_t;
enum {ESP_BT_GAP_PIN_REQ_EVT,ESP_BT_GAP_CFM_REQ_EVT,ESP_BT_GAP_KEY_REQ_EVT,ESP_BT_GAP_AUTH_CMPL_EVT,ESP_BT_GAP_KEY_NOTIF_EVT};
typedef union {
    struct {uint8_t bda[6];bool min_16_digit;} pin_req;
    struct {uint8_t bda[6];} cfm_req,key_req;
    struct {uint8_t bda[6];int stat,lk_type;} auth_cmpl;
} esp_bt_gap_cb_param_t;
enum {ESP_BT_SP_IOCAP_MODE,ESP_BT_PIN_TYPE_VARIABLE,ESP_BT_MODE_CLASSIC_BT,ESP_BT_CONTROLLER_STATUS_IDLE,ESP_BT_CONTROLLER_STATUS_INITED,ESP_BLUEDROID_STATUS_UNINITIALIZED,ESP_BLUEDROID_STATUS_ENABLED};
typedef struct {int mode;} esp_bt_controller_config_t;
#define BT_CONTROLLER_INIT_CONFIG_DEFAULT() {0}
static inline int esp_bt_controller_get_status(void) {return 99;}
static inline int esp_bt_controller_init(esp_bt_controller_config_t *p) {(void)p;return 0;}
static inline int esp_bt_controller_enable(int m) {(void)m;return 0;}
static inline int esp_bluedroid_get_status(void) {return ESP_BLUEDROID_STATUS_ENABLED;}
static inline int esp_bluedroid_init(void) {return 0;}
static inline int esp_bluedroid_enable(void) {return 0;}
static inline int esp_bt_gap_register_callback(void (*f)(esp_bt_gap_cb_event_t,esp_bt_gap_cb_param_t*)) {(void)f;return 0;}
static inline int esp_bt_gap_set_security_param(int m,void *p,size_t n) {(void)m;(void)p;(void)n;return 0;}
static inline int esp_bt_gap_pin_reply(uint8_t *p,bool a,uint8_t n,uint8_t *c) {(void)p;(void)a;(void)n;(void)c;return 0;}
static inline int esp_bt_gap_ssp_confirm_reply(uint8_t *p,bool a) {(void)p;(void)a;return 0;}
static inline int esp_bt_gap_ssp_passkey_reply(uint8_t *p,bool a,uint32_t k) {(void)p;(void)a;(void)k;return 0;}
static inline int esp_bt_gap_set_pin(int t,int n,const uint8_t *p) {(void)t;(void)n;(void)p;return 0;}
static const uint8_t peer_a[6]={1,2,3,4,5,6},peer_b[6]={6,5,4,3,2,1};
static inline int esp_bt_gap_get_bond_device_num(void) {return 2;}
static inline int esp_bt_gap_get_bond_device_list(int *n,esp_bd_addr_t *p) {assert(*n>=2);memcpy(p[0],peer_a,6);memcpy(p[1],peer_b,6);*n=2;return 0;}
typedef int esp_spp_cb_event_t;
enum {ESP_SPP_INIT_EVT,ESP_SPP_DISCOVERY_COMP_EVT,ESP_SPP_CL_INIT_EVT,ESP_SPP_OPEN_EVT,ESP_SPP_CLOSE_EVT,ESP_SPP_CONG_EVT,ESP_SPP_WRITE_EVT,ESP_SPP_DATA_IND_EVT};
enum {ESP_SPP_SUCCESS=0,ESP_SPP_SEC_AUTHENTICATE=1,ESP_SPP_SEC_ENCRYPT=2,ESP_SPP_ROLE_MASTER=0,ESP_SPP_MODE_CB=0};
typedef struct {int mode;bool enable_l2cap_ertm;int tx_buffer_size;} esp_spp_cfg_t;
typedef union {
    struct {int status;} init;
    struct {int status,scn_num;uint8_t scn[1];} disc_comp;
    struct {int status;uint32_t handle;unsigned sec_id;} cl_init;
    struct {int status;uint32_t handle;uint8_t rem_bda[6];} open;
    struct {int status;uint32_t handle;bool async;uint32_t port_status;} close;
    struct {int status;uint32_t handle;bool cong;} cong,write;
    struct {uint32_t handle;uint8_t *data;int len;} data_ind;
} esp_spp_cb_param_t;
static void (*fake_spp_event)(esp_spp_cb_event_t,esp_spp_cb_param_t*);
static uint32_t fake_handle;
static uint8_t fake_peer[6];
static unsigned fake_disconnect_failure,fake_write_fail,fake_connect_fail,fake_writes,fake_connects,fake_disconnects;
static uint8_t fake_written[65536];
static size_t fake_written_size;
static inline int esp_spp_register_callback(void (*f)(esp_spp_cb_event_t,esp_spp_cb_param_t*)) {fake_spp_event=f;return 0;}
static inline int esp_spp_enhanced_init(const esp_spp_cfg_t *c) {(void)c;esp_spp_cb_param_t p={0};fake_spp_event(ESP_SPP_INIT_EVT,&p);return 0;}
static inline int esp_spp_start_discovery(uint8_t *p) {(void)p;esp_spp_cb_param_t v={.disc_comp={0,1,{1}}};fake_spp_event(ESP_SPP_DISCOVERY_COMP_EVT,&v);return 0;}
static inline int esp_spp_connect(int sec,int role,int ch,uint8_t *p) {
    (void)role;(void)ch;assert(sec==3);fake_connects++;if(fake_connect_fail)return ESP_FAIL;memcpy(fake_peer,p,6);esp_spp_cb_param_t v={.open={.handle=++fake_handle}};memcpy(v.open.rem_bda,p,6);fake_spp_event(ESP_SPP_OPEN_EVT,&v);return 0;
}
static inline int esp_spp_disconnect(uint32_t h) {
    fake_disconnects++;if(fake_disconnect_failure==1)return ESP_FAIL;if(fake_disconnect_failure==2)return ESP_OK;
    esp_spp_cb_param_t v={.close={.handle=h}};fake_spp_event(ESP_SPP_CLOSE_EVT,&v);return 0;
}
static inline int esp_spp_write(uint32_t h,int n,uint8_t *p) {
    if(fake_write_fail)return ESP_FAIL;
    assert(fake_written_size+(size_t)n<=sizeof(fake_written));memcpy(fake_written+fake_written_size,p,n);fake_written_size+=n;fake_writes++;
    esp_spp_cb_param_t v={.write={.handle=h}};fake_spp_event(ESP_SPP_WRITE_EVT,&v);return 0;
}
