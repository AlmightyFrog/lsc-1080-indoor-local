#include <stdio.h>

/* Cross-toolchain + push-path smoke test. Built by `make`; on cam: /tmp/hello */
int main(void)
{
    printf("hello from the LSC cam hack\n");
    return 0;
}
