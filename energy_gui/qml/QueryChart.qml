import QtQuick

Canvas {
    id: plot
    required property var chart
    required property var theme
    onChartChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()
    onAvailableChanged: if (available) requestPaint()
    Connections { target: plot.theme; function onDarkChanged() { plot.requestPaint() } }
    onPaint: {
        var ctx=getContext("2d"); ctx.reset(); ctx.clearRect(0,0,width,height)
        var series=chart.series, labels=chart.labels, colors=theme.chartColors
        ctx.fillStyle=theme.ink; ctx.font="bold 12px 'Segoe UI', sans-serif"
        ctx.fillText(chart.title + (chart.unit ? " ["+chart.unit+"]" : ""),8,14)
        if (!series.length || !labels.length) return
        var lo=0, hi=0
        for (var s=0;s<series.length;++s) for(var j=0;j<series[s].values.length;++j) {
            var value=series[s].values[j]
            if(value !== null && isFinite(value)) { lo=Math.min(lo,value); hi=Math.max(hi,value) }
        }
        var totals=[]
        if(chart.kind === "stacked area") {
            for(var ti=0;ti<labels.length;++ti) {
                var total=0
                for(var ts=0;ts<series.length;++ts) total+=Math.max(0,series[ts].values[ti])
                hi=Math.max(hi,total); totals.push(0)
            }
        }
        if(hi===lo) hi=lo+1
        if (chart.kind === "horizontal bar") {
            var margin = Math.min(145, width * 0.3), barWidth = Math.max(1, width-margin-25)
            var rowHeight = (height-65)/labels.length
            var origin = margin+barWidth*(0-lo)/(hi-lo)
            ctx.font="10px 'Segoe UI', sans-serif"
            // Categorical labels are objects, not snapshots; no interpolation.
            for (var r=0; r<labels.length; ++r) {
                var v=series[0].values[r], ry=45+r*rowHeight
                ctx.fillStyle=theme.muted; ctx.textAlign="right"
                ctx.fillText(labels[r].slice(0,20),margin-8,ry+rowHeight*0.6)
                if (v === null || !isFinite(v)) continue
                var end=margin+barWidth*(v-lo)/(hi-lo)
                ctx.fillStyle=colors[0]
                ctx.fillRect(Math.min(origin,end),ry+2,Math.max(1,Math.abs(end-origin)),Math.max(1,rowHeight-5))
            }
            ctx.textAlign="left"; ctx.fillStyle=theme.muted
            ctx.fillText(lo.toPrecision(3),margin,height-8)
            ctx.textAlign="right"; ctx.fillText(hi.toPrecision(3),width-15,height-8); ctx.textAlign="left"
            return
        }
        var numericX=series.some(function(s) { return s.x_values!==undefined })
        var xCoordinates=[]
        if (numericX) series.forEach(function(s) { xCoordinates=xCoordinates.concat(s.x_values || []) })
        var xLow=numericX ? Math.min(0,Math.min.apply(null,xCoordinates)) : 0
        var xHigh=numericX ? Math.max.apply(null,xCoordinates) : 1
        var left=65, top=47, w=width-left-20, h=height-top-(numericX ? 48 : 32)
        ctx.font="10px 'Segoe UI', sans-serif"
        for(var t=0;t<5;++t) {
            var y=top+h*t/4; ctx.strokeStyle=theme.grid
            ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(left+w,y);ctx.stroke()
            ctx.fillStyle=theme.muted;ctx.fillText((hi-(hi-lo)*t/4).toPrecision(3),2,y+3)
        }
        for(var k=0;k<series.length;++k) {
            ctx.strokeStyle=colors[k%colors.length];ctx.fillStyle=colors[k%colors.length];ctx.lineWidth=2;ctx.beginPath()
            var values=series[k].values, connected=false
            if(chart.kind === "stacked area") {
                ctx.globalAlpha=0.7; ctx.beginPath()
                for(var ai=0;ai<values.length;++ai) {
                    var ax=left+w*ai/Math.max(1,values.length-1), ay=top+h*(hi-totals[ai]-Math.max(0,values[ai]))/(hi-lo)
                    if(ai===0)ctx.moveTo(ax,ay);else ctx.lineTo(ax,ay)
                }
                for(var bi=values.length-1;bi>=0;--bi)ctx.lineTo(left+w*bi/Math.max(1,values.length-1),top+h*(hi-totals[bi])/(hi-lo))
                ctx.closePath();ctx.fill();ctx.globalAlpha=1
                for(var ci=0;ci<values.length;++ci)totals[ci]+=Math.max(0,values[ci])
                ctx.fillText(series[k].name,left+k*110,33)
                continue
            }
            for(var i=0;i<values.length;++i) {
                if(values[i] === null || !isFinite(values[i])) { connected=false; continue }
                var x=numericX ? left+w*(series[k].x_values[i]-xLow)/(xHigh-xLow || 1) : left+w*i/Math.max(1,values.length-1)
                var py=top+h*(hi-values[i])/(hi-lo)
                if(chart.kind === "bar") {
                    var bw=w/Math.max(1,values.length), zero=top+h*hi/(hi-lo), slot=bw/series.length
                    ctx.fillRect(left+i*bw+k*slot+1,Math.min(zero,py),Math.max(0.5,slot-2),Math.max(1,Math.abs(zero-py)))
                } else if (chart.kind === "dot") {
                    ctx.moveTo(x+3,py); ctx.arc(x,py,3,0,2*Math.PI); ctx.fill()
                } else {
                    if(!connected)ctx.moveTo(x,py);else ctx.lineTo(x,py)
                    if(values.length === 1)ctx.fillRect(x-2,py-2,4,4)
                    connected=true
                }
            }
            ctx.stroke();ctx.fillText(series[k].name,left+k*110,33)
        }
        var labelY=height-(numericX ? 24 : 8)
        ctx.fillStyle=theme.muted;ctx.fillText(labels[0],left,labelY)
        ctx.textAlign="right";ctx.fillText(labels[labels.length-1],width-10,labelY);ctx.textAlign="left"
        if (numericX) { ctx.textAlign="center"; ctx.fillText(chart.x_label || "Numeric x",left+w/2,height-8);ctx.textAlign="left" }
    }
}
