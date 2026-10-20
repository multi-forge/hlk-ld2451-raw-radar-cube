// @category: REA
// ForceAnalyze.java - forca a analise de codigo em regioes nao cobertas (Aggressive Instruction Finder)
// e depois roda o TraceSpi.
import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.prototype.analysis.AggressiveInstructionFinderAnalyzer;
import ghidra.program.model.address.AddressSet;
import ghidra.util.task.ConsoleTaskMonitor;
import ghidra.util.exception.CancelledException;

public class ForceAnalyze extends GhidraScript {

    @Override
    public void run() throws Exception {
        ConsoleTaskMonitor mon = new ConsoleTaskMonitor();
        AggressiveInstructionFinderAnalyzer an = new AggressiveInstructionFinderAnalyzer();

        // Configura opcoes padrao
        an.setOptions(an.getDefaultOptions(), currentProgram);

        int total = 0;
        for (int round = 0; round < 4; round++) {
            AddressSet set = new AddressSet(currentProgram.getMemory().getLoadedAndInitializedAddressSet());
            boolean added = an.run(currentProgram, set, mon, new ghidra.app.util.importer.MessageLog());
            int funcs = currentProgram.getFunctionManager().getFunctionCount();
            println("### round " + round + " -> added=" + added + " funcoes=" + funcs);
            if (!added) break;
            total += funcs;
        }
        println("### TOTAL funcoes apos aggressive: " + currentProgram.getFunctionManager().getFunctionCount());
    }
}
