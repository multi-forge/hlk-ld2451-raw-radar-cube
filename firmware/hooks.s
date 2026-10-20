/*
 * Hooks do HLK-LD2451: substituem as chamadas a 0x1E15B5E (cadeia FFT)
 * por chamadas ao stub de dump, que depois chama a funcao original.
 * Preserva a ABI original (nada da funcao original e destruido).
 */
	.section .text.hook1,"ax",@progbits
	.globl hook_entry_1
	.align 2
hook_entry_1:
	call hook_stub

	.section .text.hook2,"ax",@progbits
	.globl hook_entry_2
	.align 2
hook_entry_2:
	call hook_stub
