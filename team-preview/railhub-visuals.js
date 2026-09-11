/* Product-native service visuals. All records and capacity indicators are labeled examples. */
(function(root){
  'use strict';
  const visuals={
  "uptime": "<span class=\"sv-head\"><b>Execution</b><small>Example</small></span><span class=\"sv-subhead\">Scheduled runs</span><span class=\"sv-timeline\" aria-hidden=\"true\"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i class=\"upcoming\"></i><i class=\"upcoming\"></i><i class=\"upcoming\"></i><i class=\"upcoming\"></i></span><span class=\"sv-time\"><span>06:00</span><span>12:00</span><span>18:00</span></span><span class=\"sv-line\"><span>Client brief</span><b>Completed</b></span><span class=\"sv-line\"><span>Weekly report</span><b class=\"sv-accent\">Queued</b></span>",
  "routing": "<span class=\"sv-head\"><b>Organization pool</b><small>Example</small></span><span class=\"sv-capacity\"><span><b>Workstation A</b><small>Busy</small></span><i><em style=\"width:12%\"></em></i></span><span class=\"sv-capacity chosen\"><span><b>Team server</b><small>Selected</small></span><i><em style=\"width:78%\"></em></i></span><span class=\"sv-capacity\"><span><b>Workstation B</b><small>Ready</small></span><i><em style=\"width:46%\"></em></i></span><span class=\"sv-foot\">Available capacity · approved pool</span>",
  "ledger": "<span class=\"sv-head\"><b>Run records</b><small>Example</small></span><span class=\"sv-record\"><i>01</i><span>Context read</span><b>Recorded</b></span><span class=\"sv-record\"><i>02</i><span>Draft prepared</span><b>Recorded</b></span><span class=\"sv-record\"><i>03</i><span>Review requested</span><b class=\"sv-accent\">Held</b></span><span class=\"sv-foot\"><b>#</b> Sample records · unsigned</span>",
  "library": "<span class=\"sv-head\"><b>Workflow library</b><small>Example</small></span><span class=\"sv-workflow\"><i>▤</i><span>Client brief</span><b>v2</b></span><span class=\"sv-workflow\"><i>▤</i><span>Lead follow-up</span><b>v3</b></span><span class=\"sv-workflow\"><i>▤</i><span>Weekly report</span><b>v1</b></span><span class=\"sv-foot\">Team collection · versioned work</span>"
};
  const labels={
  "uptime": "Sample execution timeline with completed and queued workflows",
  "routing": "Sample organization capacity with an available team server selected",
  "ledger": "Sample unsigned ledger with recorded actions and a review hold",
  "library": "Organized sample workflow list with separate version numbers"
};
  function render(service, detail=false) {
    if(!Object.prototype.hasOwnProperty.call(visuals,service))return '';
    return '<span class="service-visual'+(detail?' service-visual-detail':'')+'" data-service-visual="'+service+'" role="img" aria-label="'+labels[service]+'">'+visuals[service]+'</span>';
  }
  root.RailCallServiceVisuals={render};
  if(typeof module!=='undefined'&&module.exports)module.exports={render};
})(globalThis);
