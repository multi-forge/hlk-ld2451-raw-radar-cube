ENTRY(hook_stub)
SECTIONS
{
  . = 0x1E1601E;
  .text.hook1 : { *(.text.hook1) }

  . = 0x1E162CC;
  .text.hook2 : { *(.text.hook2) }

  . = 0x1E27A38;
  .text.stub : { *(.text.stub) }
}
