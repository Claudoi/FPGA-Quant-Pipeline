# fase3_322mhz_retime.tcl — variante CLO-322-01: phys_opt -retime sin cambio RTL.
# Uso (Vivado batch, desde synth/):
#   vivado -mode batch -source fase3_322mhz_retime.tcl
# Único delta vs fase3_synth.tcl: phys_opt_design -retime + un segundo
# phys_opt_design (patrón CLO-322-01). Informes en reports/322mhz_retime/
# (CLO-RPT-01: no pisar reports/322mhz/). Si WNS>=0, criterio 10 cierra sin
# tocar el book; si no, se documenta el WNS y se pasa a CLO-322-02.
set part xcku3p-ffva676-2L-e
set top itch_chain_synth
set outdir [file normalize ./reports/322mhz_retime]

file mkdir $outdir
create_project -in_memory -part $part

read_verilog -sv ../rtl/orderbook/orderbook.sv
read_verilog -sv ../rtl/parser/itch_parser.sv
read_verilog -sv ../rtl/itch_chain.sv
read_verilog -sv itch_chain_synth.sv
set_property generic {DW=32 K=64 QB=46} [current_fileset]

read_xdc constraints/fase3_322mhz.xdc

set_param synth.elaboration.rodinMoreOptions \
    "rt::set_parameter var_size_limit 9000000"
set_param general.maxThreads 8

synth_design -top $top -part $part
write_checkpoint -force $outdir/post_synth.dcp
report_utilization -hierarchical -file $outdir/util_synth.txt
report_ram_utilization -file $outdir/ram_synth.txt
report_clocks -file $outdir/clocks_synth.txt
check_timing -verbose -file $outdir/check_timing_synth.txt
report_methodology -file $outdir/methodology_synth.txt
report_timing_summary -check_timing_verbose -report_unconstrained \
    -max_paths 10 -file $outdir/timing_synth.txt

opt_design
place_design
# Delta CLO-322-01: retime + segundo phys_opt.
phys_opt_design -retime
phys_opt_design
route_design
write_checkpoint -force $outdir/post_route.dcp
report_utilization -file $outdir/util_impl.txt
report_ram_utilization -file $outdir/ram_impl.txt
check_timing -verbose -file $outdir/check_timing_impl.txt
report_methodology -file $outdir/methodology_impl.txt
report_drc -file $outdir/drc_impl.txt
report_timing_summary -check_timing_verbose -report_unconstrained \
    -max_paths 10 -file $outdir/timing_impl.txt

set violating_paths [get_timing_paths -delay_type max -slack_lesser_than 0.0 \
    -max_paths 1 -quiet]
if {[llength $violating_paths] != 0} {
    set wns [get_property SLACK [lindex $violating_paths 0]]
    error "FASE3 RETIME TIMING FAIL: WNS=$wns ns (se exige WNS>=0 y TNS=0)"
}

puts "== FASE3 RETIME SYNTH/IMPL OK — informes en $outdir =="