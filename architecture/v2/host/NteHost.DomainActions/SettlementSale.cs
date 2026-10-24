namespace NteHost.DomainActions;

// C02's six quality circles, measured relative to settlement_grid_bounds.
// Read the ring, never infer selection from the colour of the item itself.
public sealed record SettlementSale(bool[] Selected, long? Funds = null, bool Sold = false)
{
    public bool Ready => Selected.Length == 6 && Selected.Take(5).All(x => x) && !Selected[5];
    public static readonly DomainPrimitive[] Toggles = [DomainPrimitive.SaleWhite, DomainPrimitive.SaleGreen,
        DomainPrimitive.SaleBlue, DomainPrimitive.SalePurple, DomainPrimitive.SaleGold, DomainPrimitive.SaleRed];
    static readonly double[] Positions = [.081, .251, .422, .588, .758, .929];
    public static (int X, int Y, int Radius) Circle(int width, int height, int index)
    {
        int x1=(int)Math.Round(width*1315.0/1920), x2=(int)Math.Round(width*1878.0/1920);
        int y1=(int)Math.Round(height*214.0/1080), y2=(int)Math.Round(height*776.0/1080);
        return (x1+(int)Math.Round(Positions[index]*(x2-x1)), y2+(int)Math.Round(.052*(y2-y1)),
            (int)Math.Round(.035*(x2-x1)));
    }
    public static SettlementSale? Read(NativeDomainFrame f)
    {
        int w=f.Geometry.Width,h=f.Geometry.Height,valid=0;
        var pixels=f.Pixels.Span; var result=new bool[6];
        int gridW=(int)Math.Round(w*1878.0/1920)-(int)Math.Round(w*1315.0/1920);
        int inner=(int)Math.Round(.021*gridW);
        for(int i=0;i<6;i++) {
            var (cx,cy,outer)=Circle(w,h,i); int search=(int)Math.Round(outer*1.25),pink=0;
            if(cx-search<0 || cy-search<0 || cx+search>=w || cy+search>=h) return null;
            int center=cy*f.Stride+cx*4;
            if(Math.Max(pixels[center],Math.Max(pixels[center+1],pixels[center+2]))>50) valid++;
            for(int dy=-search;dy<=search;dy++) for(int dx=-search;dx<=search;dx++) {
                double distance=Math.Sqrt(dx*dx+dy*dy);
                if(distance<inner*1.15 || distance>outer*1.25) continue;
                int p=(cy+dy)*f.Stride+(cx+dx)*4;
                int b=pixels[p],g=pixels[p+1],r=pixels[p+2],max=Math.Max(r,Math.Max(g,b)),min=Math.Min(r,Math.Min(g,b));
                if(r>150 && b>110 && g<115 && max>0 && (max-min)*255.0/max>65) pink++;
            }
            result[i]=pink>=Math.Max(5,(int)(outer*.8));
        }
        return valid>=4 ? new(result) : null;
    }
}
