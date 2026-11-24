#include "p68_afe_flow.h"
#include <string.h>

/* Apply +12.04 dB only to the microphone channels, not the AEC reference. */
static int16_t mic_gain(int16_t sample)
{
    int32_t scaled=(int32_t)sample*4;
    return scaled>INT16_MAX ? INT16_MAX : scaled<INT16_MIN ? INT16_MIN : (int16_t)scaled;
}

void tivoo_afe_interleave(int16_t *out, const int16_t *left,
    const int16_t *right, const int16_t *ref, size_t count)
{
    for (size_t i=0; i<count; ++i) {
        out[4*i]=mic_gain(left[i]);
        out[4*i+1]=mic_gain(right[i]);
        out[4*i+2]=0;
        out[4*i+3]=ref[i];
    }
}

static void emit(tivoo_afe_flow_t *f, tivoo_afe_event_type_t type,
    uint64_t index, const int16_t *pcm, size_t count, int word)
{
    if (f->sink) {
        const tivoo_afe_event_t event={type,index,pcm,count,word};
        f->sink(f->ctx,&event);
    }
}

void tivoo_afe_flow_init(tivoo_afe_flow_t *f, int words, tivoo_afe_sink_t sink, void *ctx)
{
    memset(f,0,sizeof(*f));
    f->words=words;
    f->sink=sink;
    f->ctx=ctx;
}

void tivoo_afe_flow_close(tivoo_afe_flow_t *f)
{
    f->gate_open=f->speaking=f->onset_guard=false;
    f->write=f->history_count=0;
}

bool tivoo_afe_flow_open(tivoo_afe_flow_t *f, uint64_t first)
{
    if (f->gate_open || f->prompt || (f->have_next && first<f->next)) {
        emit(f,TIVOO_AFE_GAP,f->next,NULL,0,0);
        tivoo_afe_flow_close(f);
        return false;
    }
    f->gate=first;
    f->gate_open=true;
    f->onset_guard=true;
    return true;
}

void tivoo_afe_flow_prompt(tivoo_afe_flow_t *f, bool suppress, uint64_t wake_after)
{
    if (suppress && f->gate_open) emit(f,TIVOO_AFE_GAP,f->next,NULL,0,0);
    tivoo_afe_flow_close(f);
    f->candidate=0;
    f->latched=false;
    f->prompt=suppress;
    f->prompt_rearm=true;
    f->wake_after=wake_after;
}

void tivoo_afe_flow_gap(tivoo_afe_flow_t *f)
{
    emit(f,TIVOO_AFE_GAP,f->next,NULL,0,0);
    tivoo_afe_flow_close(f);
    f->candidate=0;
    f->latched=false;
    f->have_next=false;
}

static int detect(tivoo_afe_flow_t *f, uint64_t first, int state,
    int raw, int model, int word)
{
    if (f->prompt || first<f->wake_after) {
        f->candidate=0;
        f->latched=false;
        return 0;
    }
    if (state==0) {
        f->prompt_rearm=false;
        f->latched=false;
        return 0;
    }
    if (f->latched || f->prompt_rearm) return 0;
    const bool valid=model==1 && word>0 && word<=f->words;
    if (state==1) {
        f->candidate=raw>1 && valid ? word : 0;
        if (raw!=1 || !valid) return 0;
    } else if (state==-1 && raw>1 && f->candidate) {
        if ((model!=0 && model!=1) || (word!=0 && word!=f->candidate)) {
            f->candidate=0;
            return 0;
        }
        word=f->candidate;
    } else {
        f->candidate=0;
        return 0;
    }
    f->candidate=0;
    f->latched=true;
    return word;
}

static void remember(tivoo_afe_flow_t *f, const int16_t *pcm, size_t count)
{
    for (size_t i=0;i<count;++i) {
        f->history[f->write]=pcm[i];
        f->write=(f->write+1)%TIVOO_AFE_HISTORY_SAMPLES;
        if (f->history_count<TIVOO_AFE_HISTORY_SAMPLES) ++f->history_count;
    }
}

static void start(tivoo_afe_flow_t *f, uint64_t first)
{
    size_t count=f->history_count;
    uint64_t index=first-count;
    size_t read=(f->write+TIVOO_AFE_HISTORY_SAMPLES-count)%TIVOO_AFE_HISTORY_SAMPLES;
    emit(f,TIVOO_AFE_START,index,NULL,0,0);
    while (count) {
        size_t n=TIVOO_AFE_HISTORY_SAMPLES-read;
        if (n>count) n=count;
        emit(f,TIVOO_AFE_PCM,index,f->history+read,n,0);
        index+=n;
        count-=n;
        read=0;
    }
    f->history_count=0;
    f->speaking=true;
}

void tivoo_afe_flow_frame(tivoo_afe_flow_t *f, uint64_t first, const int16_t *pcm,
    size_t count, bool speech, bool vad_valid, int wake_state, int raw_channels,
    int model, int word, size_t cache_samples)
{
    if (!pcm || !count || count>UINT64_MAX-first ||
        (f->have_next && first!=f->next)) {
        tivoo_afe_flow_gap(f);
        return;
    }
    f->have_next=true;
    f->next=first+count;
    /* All successful enhanced frames, including silence, are retained once.
     * ESP-SR cache has no sample index. Never blindly prepend overlapping data. */
    f->cache_ignored+=cache_samples;
    const int confirmed=detect(f,first,wake_state,raw_channels,model,word);
    if (confirmed) {
        tivoo_afe_flow_close(f);
        emit(f,TIVOO_AFE_WAKE,first,NULL,0,confirmed);
        return;
    }
    if (!f->gate_open || f->prompt || f->next<=f->gate) return;
    const bool crosses_gate=first<f->gate;
    if (crosses_gate) {
        size_t skip=f->gate-first;
        pcm+=skip;
        count-=skip;
        first=f->gate;
        /* A VAD decision covering pre-gate samples is not command speech. */
        vad_valid=false;
    }
    /* Preserve post-gate samples even when their VAD decision predates
     * the gate reset. They cannot establish either speech or neutrality. */
    if (!vad_valid) {
        if (f->speaking) tivoo_afe_flow_gap(f);
        else remember(f,pcm,count);
        return;
    }
    /* Reject digital silence at ambiguous onset, without inventing a
     * second acoustic threshold or waiting for a silence transition. */
    if (!f->speaking && f->onset_guard) {
        if (!speech) f->onset_guard=false;
        else {
            bool nonzero=false;
            for (size_t i=0;i<count;i++) {
                if (pcm[i]) { nonzero=true; break; }
            }
            if (!nonzero) speech=false;
            else f->onset_guard=false;
        }
    }
    if (!f->speaking && !speech) {
        remember(f,pcm,count);
        return;
    }
    if (!f->speaking) start(f,first);
    emit(f,TIVOO_AFE_PCM,first,pcm,count,0);
    if (!speech) {
        emit(f,TIVOO_AFE_END,f->next,NULL,0,0);
        tivoo_afe_flow_close(f);
    }
}
