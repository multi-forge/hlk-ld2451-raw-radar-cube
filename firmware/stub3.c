/*
 * HLK-LD2451 - stub de dump do cubo bruto (pi32v2), injetado em code cave.
 *
 * Chamado no lugar da cadeia FFT (0x1E15B5E). Envia o cubo 64x256
 * empacotado (0x15B60, 0x4000 bytes) pela UART0 e depois executa a
 * funcao original, de modo que o comportamento do radar e preservado.
 *
 * Flag de controle em 0x1E27A34 (4 bytes, little-endian):
 *    0 = desligado (comportamento identico ao firmware original)
 *    1 = one-shot  (desliga o flag apos um dump)
 *    2 = continuo  (dumps a cada chamada)
 */
typedef void (*uart_send_fn)(void *buf, unsigned len);
typedef void (*void_fn)(void);

#define CAVE_FLAG   0x1E27A34u
#define CUBE_PTR    0x15B60u
#define CUBE_LEN    0x4000u
#define UART0_SEND  0x1E115FAu
#define ORIG_FFT    0x1E15B5Eu

__attribute__((section(".text.stub")))
void hook_stub(void)
{
    unsigned mode = *(volatile unsigned int *)CAVE_FLAG;

    if (mode != 0) {
        unsigned char hdr[12];
        unsigned char *p;
        unsigned i;

        hdr[0] = 0xAA; hdr[1] = 0xBB; hdr[2] = 0xCC; hdr[3] = 0xDD;
        for (i = 0; i < 4; i++)
            hdr[4 + i] = (unsigned char)(CUBE_LEN >> (8 * i));
        for (i = 0; i < 4; i++)
            hdr[8 + i] = 0;

        ((uart_send_fn)UART0_SEND)(hdr, 12);

        p = (unsigned char *)CUBE_PTR;
        for (i = 0; i < CUBE_LEN; i += 512) {
            unsigned n = CUBE_LEN - i;
            if (n > 512) n = 512;
            ((uart_send_fn)UART0_SEND)(p + i, n);
        }

        if (mode == 1)
            *(volatile unsigned int *)CAVE_FLAG = 0;
    }

    /* executa a cadeia FFT original: os registers r0-r3 ficam como antes */
    ((void_fn)ORIG_FFT)();
}
