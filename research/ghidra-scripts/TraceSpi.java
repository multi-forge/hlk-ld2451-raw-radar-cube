// @category: REA
// TraceSpi.java - rastreia o driver SPI0 (link com o radar RC2412FR) no firmware AC635N
// Uso: ... -postScript TraceSpi.java
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class TraceSpi extends GhidraScript {

    private DecompInterface di;

    private String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    private byte[] leBytes(int value) {
        return new byte[]{(byte) value, (byte) (value >> 8), (byte) (value >> 16), (byte) (value >> 24)};
    }

    @Override
    public void run() throws Exception {
        di = new DecompInterface();
        di.openProgram(currentProgram);

        // Bases de perifericos calculadas dos headers do SDK BR23 (ls_base=0x1e0000, hs_base=0x1f0000)
        Map<String, Integer> bases = new LinkedHashMap<>();
        bases.put("SPI0",   0x1E01C00);
        bases.put("SPI1",   0x1E01D00);
        bases.put("SPI2",   0x1E01E00);
        bases.put("SFC",    0x1F0200);
        bases.put("SFCENC", 0x1F0300);
        bases.put("PORTA",  0x1E05000);
        bases.put("PORTB",  0x1E05040);
        bases.put("PORTC",  0x1E05080);

        MemoryBlock block = null;
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            if (b.isInitialized() && b.getSize() > 0x100000 && b.getName().startsWith("segment")) {
                block = b;
                break;
            }
        }
        if (block == null) {
            for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
                if (b.isInitialized()) { block = b; break; }
            }
        }
        println("### bloco analisado: " + block.getName() + " (" + block.getSize() + " bytes)");

        int sz = (int) Math.min(block.getSize(), 0x400000);
        byte[] buf = new byte[sz];
        block.getBytes(block.getStart(), buf);

        Map<Function, List<String>> hits = new LinkedHashMap<>();

        for (Map.Entry<String, Integer> e : bases.entrySet()) {
            byte[] needle = leBytes(e.getValue());
            int off = 0;
            while (true) {
                off = indexOf(buf, needle, off);
                if (off < 0) break;
                Address a = block.getStart().add(off);
                Function fn = getFunctionContaining(a);
                String key = e.getKey() + "(" + String.format("0x%08X", e.getValue()) + ")@" + a;
                if (fn == null) {
                    hits.computeIfAbsent(null, k -> new ArrayList<>()).add(key);
                } else {
                    hits.computeIfAbsent(fn, k -> new ArrayList<>()).add(key);
                }
                off++;
            }
        }

        println("### total de funcoes com referencias a perifericos: " + hits.size());
        int n = 0;
        for (Map.Entry<Function, List<String>> entry : hits.entrySet()) {
            n++;
            Function fn = entry.getKey();
            println("\n==============================================================================");
            if (fn == null) {
                println("### FORA DE FUNCAO (dados) - " + entry.getValue().size() + " refs");
                for (String s : entry.getValue()) println("    " + s);
                continue;
            }
            println("### [" + n + "] " + fn.getName() + " @" + fn.getEntryPoint()
                    + " tamanho=" + fn.getBody().getNumAddresses() + " refs=" + entry.getValue().size());
            for (String s : entry.getValue()) println("      ref: " + s);
            DecompileResults r = di.decompileFunction(fn, 120, monitor);
            if (r.decompileCompleted()) {
                println(r.getDecompiledFunction().getC());
            } else {
                println("    DECOMPILE FALHOU: " + r.getErrorMessage());
                // fallback: listagem
                Instruction ins = getInstructionAt(fn.getEntryPoint());
                if (ins == null) ins = getInstructionAfter(fn.getEntryPoint());
                int c = 0;
                while (ins != null && c < 60) {
                    println("      " + ins.getAddress() + "  " + ins.toString());
                    ins = ins.getNext();
                    c++;
                }
            }
        }
    }

    private int indexOf(byte[] haystack, byte[] needle, int from) {
        outer:
        for (int i = from; i + needle.length <= haystack.length; i++) {
            for (int j = 0; j < needle.length; j++) {
                if (haystack[i + j] != needle[j]) continue outer;
            }
            return i;
        }
        return -1;
    }
}
