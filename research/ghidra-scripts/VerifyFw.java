// @category REA
// Verifica alegacoes da pesquisa anterior sobre o firmware HLK-LD2451 (AC635N/BR23, pi32v2)
// Uso: analyzeHeadless <proj> <name> -process <prog> -noanalysis -postScript VerifyFw.java ARGS
//   addr:0x1E10BA6       -> decompila a funcao nesse endereco
//   table:0x1E21A34:40   -> le N pares (u32 id, u32 handler) a partir do endereco
//   val:0x0001E230       -> procura o valor LE de 32 bits e lista referencias
//   pat:fdfcfbfa         -> procura padrao de bytes (hex) e lista referencias
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Reference;

import java.util.List;

public class VerifyFw extends GhidraScript {

    private DecompInterface di;

    private Address addr(String hex) {
        if (hex.startsWith("0x") || hex.startsWith("0X")) {
            hex = hex.substring(2);
        }
        return currentProgram.getAddressFactory().getAddress(hex);
    }

    private int readU32(Address a) throws Exception {
        byte[] b = new byte[4];
        currentProgram.getMemory().getBytes(a, b);
        return ((b[3] & 0xff) << 24) | ((b[2] & 0xff) << 16) | ((b[1] & 0xff) << 8) | (b[0] & 0xff);
    }

    private void doAddr(String spec) {
        Address addr = addr(spec);
        Function fn = ensureFunction(addr);
        println("### FUNCAO @ " + addr + (fn != null ? "  entry=" + fn.getEntryPoint() : ""));
        if (fn == null) {
            println("    NAO ENCONTRADA funcao nesse endereco");
            return;
        }
        println("    tamanho=" + fn.getBody().getNumAddresses());
        DecompileResults r = di.decompileFunction(fn, 90, monitor);
        if (r.decompileCompleted()) {
            println(r.getDecompiledFunction().getC());
        } else {
            println("    DECOMPILE FALHOU: " + r.getErrorMessage());
        }
    }

    private void doTable(String spec) throws Exception {
        String[] p = spec.split(":");
        Address base = addr(p[0]);
        int n = p.length > 1 ? Integer.parseInt(p[1]) : 32;
        println("### TABELA @ " + base + " (" + n + " slots de 8 bytes)");
        for (int i = 0; i < n; i++) {
            Address slot = base.add(i * 8);
            int cid = readU32(slot);
            int h = readU32(slot.add(4));
            if (h == 0 || h > 0x8000000) {
                println(String.format("  %-12s id=0x%04x fn=0x%x  <-- fim/corrompido", slot, cid, h));
                break;
            }
            Address ha = addr(String.format("%x", h));
            String name = "?";
            Function f = getFunctionAt(ha);
            if (f == null) {
                f = getFunctionContaining(ha);
            }
            if (f != null) {
                name = f.getName() + "@" + f.getEntryPoint();
            }
            println(String.format("  %-12s id=0x%04x fn=0x%x  tratar=%s", slot, cid, h, name));
        }
    }

    private void searchBytes(String label, byte[] needle) {
        println("### " + label + " ocorrencias de " + toHex(needle));
        int total = 0;
        for (MemoryBlock blk : currentProgram.getMemory().getBlocks()) {
            if (!blk.isInitialized()) {
                continue;
            }
            long sz = blk.getSize();
            if (sz > 0x400000) {
                continue;
            }
            byte[] buf = new byte[(int) sz];
            try {
                blk.getBytes(blk.getStart(), buf);
            } catch (Exception e) {
                continue;
            }
            for (int i = 0; i + needle.length <= buf.length; i++) {
                boolean ok = true;
                for (int j = 0; j < needle.length; j++) {
                    if (buf[i + j] != needle[j]) {
                        ok = false;
                        break;
                    }
                }
                if (!ok) {
                    continue;
                }
                total++;
                Address a = blk.getStart().add(i);
                StringBuilder sb = new StringBuilder();
                sb.append("  @ ").append(a).append("  bloco=").append(blk.getName());
                Function fn = getFunctionContaining(a);
                sb.append("  funcao=").append(fn != null ? fn.getName() + "@" + fn.getEntryPoint() : "?");
                for (Reference r : getReferencesTo(a)) {
                    sb.append("\n      xref de ").append(r.getFromAddress()).append(" (").append(r.getReferenceType()).append(")");
                }
                println(sb.toString());
                if (total > 60) {
                    println("  ... (truncado)");
                    return;
                }
            }
        }
        if (total == 0) {
            println("  (nenhuma ocorrencia)");
        }
    }

    private String toHex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) {
            sb.append(String.format("%02x", x));
        }
        return sb.toString();
    }


    private void doDis(String spec) {
        String[] p = spec.split(":");
        Address a = addr(p[0]);
        int n = p.length > 1 ? Integer.parseInt(p[1]) : 40;
        println("### LISTAGEM @ " + a + " (" + n + " instrucoes)");
        try {
            DisassembleCommand dc = new DisassembleCommand(a, null, true);
            dc.applyTo(currentProgram, monitor);
        } catch (Exception e) {
            println("  desmontagem: " + e);
        }
        Instruction ins = getInstructionAt(a);
        if (ins == null) {
            ins = getInstructionAfter(a);
        }
        int c = 0;
        while (ins != null && c < n) {
            println(String.format("  %-14s %-30s %s", ins.getAddress(), ins.getMnemonicString(),
                    ins.toString().replace(ins.getMnemonicString() + " ", "")));
            ins = ins.getNext();
            c++;
        }
        println("  (total listado: " + c + ")");
    }

    private void doXref(String spec) {
        Address a = addr(spec);
        println("### XREFS -> " + a);
        int c = 0;
        for (Reference r : getReferencesTo(a)) {
            println("  " + r.getFromAddress() + " (" + r.getReferenceType() + ")");
            c++;
        }
        if (c == 0) {
            println("  (nenhuma)");
        }
    }

    private Function ensureFunction(Address a) {
        Function fn = getFunctionAt(a);
        if (fn != null) {
            return fn;
        }
        try {
            new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
        } catch (Exception e) {
            // ignora
        }
        try {
            new CreateFunctionCmd(null, a, null, SourceType.ANALYSIS, false, true).applyTo(currentProgram, monitor);
        } catch (Exception e) {
            // ignora
        }
        return getFunctionAt(a);
    }

    @Override
    public void run() throws Exception {
        di = new DecompInterface();
        di.openProgram(currentProgram);
        String[] args = getScriptArgs();
        println("### PROGRAMA: " + currentProgram.getName() + " imagem base=" + currentProgram.getImageBase()
                + " funcoes=" + currentProgram.getFunctionManager().getFunctionCount());
        if (args.length == 0) {
            println("sem argumentos");
            return;
        }
        for (String a : args) {
            int c = a.indexOf(':');
            String kind = c < 0 ? a : a.substring(0, c);
            String rest = c < 0 ? "" : a.substring(c + 1);
            println("\n" + "==============================================================================");
            if (kind.equals("dis")) {
                doDis(rest);
            } else if (kind.equals("xref")) {
                doXref(rest);
            } else if (kind.equals("addr")) {
                doAddr(rest);
            } else if (kind.equals("table")) {
                doTable(rest);
            } else if (kind.equals("val")) {
                int v = (int) Long.parseLong(rest.replace("0x", ""), 16);
                searchBytes("VALOR 0x" + Long.toHexString(v & 0xffffffffL),
                        new byte[]{(byte) v, (byte) (v >> 8), (byte) (v >> 16), (byte) (v >> 24)});
            } else if (kind.equals("pat")) {
                byte[] nb = new byte[rest.length() / 2];
                for (int i = 0; i < nb.length; i++) {
                    nb[i] = (byte) Integer.parseInt(rest.substring(i * 2, i * 2 + 2), 16);
                }
                searchBytes("PADRAO", nb);
            } else {
                println("argumento desconhecido: " + a);
            }
        }
    }
}
