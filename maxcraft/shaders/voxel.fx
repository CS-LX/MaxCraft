// MaxCraft: nearest-sampled Minecraft texture, with depth-writing alpha cutout.
float4x4 WorldViewProjection : WorldViewProjection < string UIWidget="None"; >;
Texture2D Sprite : DiffuseMap <
    string UIName="Minecraft texture";
    string ResourceType="2D";
    int Texcoord=0;
    int MapChannel=1;
>;
SamplerState PixelSampler {
    Filter=MIN_MAG_MIP_POINT;
    // Max's DirectX UV stream wraps V; clamp collapses it into one texture row.
    AddressU=Wrap;
    AddressV=Wrap;
};
struct VertexIn { float4 position:POSITION; float2 uv:TEXCOORD0; };
struct VertexOut { float4 position:SV_Position; float2 uv:TEXCOORD0; };
VertexOut VS(VertexIn v) {
    VertexOut o;
    o.position=mul(v.position, WorldViewProjection);
    o.uv=v.uv;
    return o;
}
float4 CutoutPS(VertexOut v):SV_Target {
    float4 color=Sprite.Sample(PixelSampler,v.uv);
    clip(color.a-0.5);
    return float4(color.rgb,1);
}
BlendState SolidBlend { BlendEnable[0]=false; RenderTargetWriteMask[0]=15; };
technique11 Cutout {
    pass P0 {
        SetBlendState(SolidBlend,float4(0,0,0,0),0xffffffff);
        SetVertexShader(CompileShader(vs_5_0,VS()));
        SetGeometryShader(NULL);
        SetPixelShader(CompileShader(ps_5_0,CutoutPS()));
    }
}
