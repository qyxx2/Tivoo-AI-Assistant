#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "audio_pcm_buffer.h"

int main(void)
{
    uint8_t storage[16], input[24], output[24];
    for (unsigned i=0; i<sizeof(input); ++i) input[i]=(uint8_t)i;
    tivoo_pcm_buffer_t b;
    tivoo_pcm_buffer_init(&b,storage,sizeof(storage));
    assert(tivoo_pcm_buffer_size(&b)==0);
    assert(!tivoo_pcm_buffer_ready(&b,8,false));
    assert(tivoo_pcm_buffer_push(&b,input,7)==7);
    assert(!tivoo_pcm_buffer_ready(&b,8,false));
    assert(tivoo_pcm_buffer_ready(&b,8,true)); /* short reply at EOF */
    assert(tivoo_pcm_buffer_push(&b,input+7,14)==9);
    assert(tivoo_pcm_buffer_size(&b)==16);
    assert(tivoo_pcm_buffer_ready(&b,8,false));
    assert(tivoo_pcm_buffer_push(&b,input,1)==0);
    assert(tivoo_pcm_buffer_pop(&b,output,11)==11);
    assert(tivoo_pcm_buffer_push(&b,input+16,8)==8); /* wrap */
    assert(tivoo_pcm_buffer_pop(&b,output+11,13)==13);
    assert(!memcmp(input,output,sizeof(input)));
    assert(tivoo_pcm_buffer_pop(&b,output,1)==0);
    assert(!tivoo_pcm_buffer_ready(&b,8,true));
    return 0;
}
