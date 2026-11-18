#include "p68_prompt.h"

int tivoo_prompt_select(const tivoo_prompt_asset_t pool[4], bool followup, int last, unsigned random)
{
    if (followup) return pool[3].pcm && pool[3].samples ? 3 : -1;
    int choices[3], n=0;
    for (int i=0;i<3;++i)
        if (i!=last && pool[i].pcm && pool[i].samples) choices[n++]=i;
    return n ? choices[random%(unsigned)n] : -1;
}

void tivoo_prompt_begin(tivoo_prompt_t *p, tivoo_prompt_asset_t asset, uint64_t now, unsigned tail, int offset)
{
    *p=(tivoo_prompt_t){.asset=asset,.started_ms=now,.tail=tail,.offset=offset,
        .skipped=!asset.pcm || !asset.samples};
}
void tivoo_prompt_cancel(tivoo_prompt_t *p) { p->cancelled=true; }

tivoo_prompt_status_t tivoo_prompt_poll(tivoo_prompt_t *p, const tivoo_prompt_io_t *io, void *ctx, uint64_t now)
{
    if (now-p->started_ms>=5000) p->cancelled=true;
    if (p->cancelled && !p->stopping) {
        io->stop(ctx);
        p->stopping=true;
    }
    if (!p->cancelled && !p->finished) {
        if (!p->skipped)
            p->written+=io->push(ctx,p->asset.pcm+p->written,p->asset.samples-p->written);
        if (p->skipped || p->written==p->asset.samples) {
            io->finish(ctx);
            p->finished=true;
        }
    }
    uint64_t end, clock;
    if ((p->finished || p->stopping) && io->drain(ctx,&end,&clock)) {
        if (!p->drained) {
            p->physical_gate=end+p->tail;
            p->drained=true;
        }
        if (clock>=p->physical_gate) {
            const int64_t mapped=(int64_t)p->physical_gate+p->offset;
            if (mapped<0) p->cancelled=true;
            p->gate_sample=mapped<0 ? 0 : (uint64_t)mapped;
            const uint64_t late=(clock-p->physical_gate)/16;
            p->gate_ms=late>now ? 0 : now-late;
            return TIVOO_PROMPT_SAFE;
        }
    }
    return p->cancelled ? TIVOO_PROMPT_UNSAFE : TIVOO_PROMPT_PENDING;
}
