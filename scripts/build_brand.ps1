# Export the generated artwork to the PNG sizes used by HA and Supervisor.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
public static class TrussBrandExport {
    public static void Export(string source, string output, int size) {
        using (var image = new Bitmap(source)) {
            int left=image.Width, top=image.Height, right=-1, bottom=-1;
            for (int y=0; y<image.Height; y++)
                for (int x=0; x<image.Width; x++)
                    if (image.GetPixel(x,y).A > 8) {
                        left=Math.Min(left,x); right=Math.Max(right,x);
                        top=Math.Min(top,y); bottom=Math.Max(bottom,y);
                    }
            if (right < left) throw new Exception("Source image is empty");
            float width=right-left+1, height=bottom-top+1;
            float scale=(size-4)/Math.Max(width,height);
            using (var canvas=new Bitmap(size,size,PixelFormat.Format32bppArgb)) {
                using (var graphics=Graphics.FromImage(canvas)) {
                    graphics.Clear(Color.Transparent);
                    graphics.CompositingQuality=CompositingQuality.HighQuality;
                    graphics.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    graphics.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    graphics.DrawImage(image,
                        new RectangleF((size-width*scale)/2,(size-height*scale)/2,width*scale,height*scale),
                        new RectangleF(left,top,width,height),GraphicsUnit.Pixel);
                }
                canvas.Save(output,ImageFormat.Png);
            }
        }
    }
}
'@
$trussRoot = Split-Path -Parent $PSScriptRoot
$trussSource = Join-Path $trussRoot 'assets/truss-icon-source.png'
$trussBrand = Join-Path $trussRoot 'custom_components/truss/brand'
New-Item -ItemType Directory -Force $trussBrand | Out-Null
foreach ($trussSize in @(256,512)) {
    $trussSuffix = if ($trussSize -eq 512) { '@2x' } else { '' }
    $trussIcon = Join-Path $trussBrand ('icon' + $trussSuffix + '.png')
    [TrussBrandExport]::Export($trussSource,$trussIcon,$trussSize)
    foreach ($trussName in @('dark_icon','logo','dark_logo')) {
        Copy-Item -LiteralPath $trussIcon -Destination (Join-Path $trussBrand ($trussName + $trussSuffix + '.png'))
    }
}
Copy-Item -LiteralPath (Join-Path $trussBrand 'icon.png') -Destination (Join-Path $trussRoot 'icon.png')
Copy-Item -LiteralPath (Join-Path $trussBrand 'logo.png') -Destination (Join-Path $trussRoot 'truss_engine/logo.png')
[TrussBrandExport]::Export($trussSource,(Join-Path $trussRoot 'truss_engine/icon.png'),128)
Write-Output 'Exported transparent icons for the integration, repository, and companion app.'
